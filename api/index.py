import os
import asyncio
import base64
import httpx
import uvicorn
import aiofiles
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# Try-except block to handle different import contexts (local vs vercel)
try:
    from .storage import StorageManager
except ImportError:
    from storage import StorageManager

storage_manager = StorageManager()


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Vercel handles static files from /public automatically. No need to mount.
# But for local dev we might miss it. However, the priority is Vercel fix.

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
RUNPOD_ENDPOINT_ID = "hgn3kb2km6tnxi"
RUNPOD_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run"
RUNPOD_STATUS_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status"

HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json"
}

# 10 minute timeout for RunPod in case of slow queue
TIMEOUT_SETTINGS = httpx.Timeout(600.0, connect=60.0)

@app.post("/api/upscale")
async def upscale_video(
    file: UploadFile = File(...),
    target_resolution: str = "1920x1080"
):
    print(f"Received file: {file.filename} | Target: {target_resolution}")
    
    # Parse resolution
    try:
        w, h = target_resolution.split("x")
        target_width = int(w)
        target_height = int(h)
    except:
        target_width, target_height = 1920, 1080

    # 1. Read and Encode Video (Keep Base64 input for simplicty of RunPod Handler V1, 
    # but optimally we should upload Input to R2 too. For now let's keep input as Base64 to not break too much)
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
            
        video_base64 = base64.b64encode(content).decode('utf-8')
        print(f"Video encoded to base64. Size: {len(video_base64) / 1024 / 1024:.2f} MB")
        
    except Exception as e:
        print(f"Error reading/encoding file: {e}")
        raise HTTPException(status_code=500, detail="Failed to process video file")

    # 2. Prepare R2 Upload for OUTPUT
    # We tell RunPod: "When you are done, PUT the file to this URL"
    output_filename = f"upscaled_{int(time.time())}_{file.filename}"
    output_object_key = f"outputs/{output_filename}"
    
    # Generate Presigned Upload URL for RunPod to use
    presigned_upload_url = storage_manager.generate_presigned_upload_url(output_object_key)
    if not presigned_upload_url:
        print("Warning: Could not generate R2 Upload URL. RunPod logic might fail if relying on it.")
        # We continue, but RunPod might fallback to base64 if handler handles it.

    # 3. Send to RunPod
    payload = {
        "input": {
            "video": video_base64,
            "target_width": target_width,
            "target_height": target_height,
            "output_upload_url": presigned_upload_url # This is the key for updated_handler.py
        }
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT_SETTINGS) as client:
        try:
            print("Sending request to RunPod...")
            response = await client.post(RUNPOD_URL, headers=HEADERS, json=payload)
            
            if response.status_code != 200:
                print(f"RunPod Error Status: {response.status_code}")
                # Check for 401 specifically
                if response.status_code == 401:
                    raise HTTPException(status_code=401, detail="RunPod Authentication Failed. Check API Key.")
                
                raise HTTPException(status_code=502, detail=f"RunPod Error ({response.status_code}): {response.text[:200]}")
            
            try:
                data = response.json()
            except ValueError:
                 raise HTTPException(status_code=502, detail=f"RunPod returned invalid JSON: {response.text[:200]}")

            request_id = data.get("id")
            print(f"RunPod Request ID: {request_id}")
            
        except httpx.RequestError as e:
            print(f"RunPod Connection Error: {e}")
            raise HTTPException(status_code=502, detail=f"RunPod Connection Error: {str(e)}")

        # 4. Poll for Status
        status = "IN_PROGRESS"
        
        while status in ["IN_PROGRESS", "IN_QUEUE"]:
            await asyncio.sleep(2)  # Non-blocking sleep
            try:
                status_resp = await client.get(f"{RUNPOD_STATUS_URL}/{request_id}", headers=HEADERS)
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status")
                print(f"Polling Status: {status}")
                
                if status == "COMPLETED":
                    # Smart Logic:
                    # If we sent an output_upload_url, RunPod should have used it.
                    # RunPod response `output` might be a message like "Output uploaded..." 
                    # OR if the user didn't update the handler yet, it might doubtless contain the base64.
                    
                    output_data = status_data.get("output", {})
                    
                    # Check if R2 integration worked
                    # If we generated a URL, and status is success, we trust it or check metadata
                    
                    # Generate a VIEW URL (Download URL) from R2
                    if presigned_upload_url:
                        # Assuming success upload
                        view_url = storage_manager.generate_presigned_download_url(output_object_key)
                        if view_url:
                            print(f"Generated R2 View URL: {view_url[:50]}...")
                            return JSONResponse({"url": view_url, "type": "r2_url"})
                    
                    # Fallback: Handle Base64 if Handler didn't use R2
                    bg_video_str = None
                    if isinstance(output_data, dict):
                        bg_video_str = output_data.get("video") or output_data.get("output_video")
                    elif isinstance(output_data, str):
                        bg_video_str = output_data

                    if bg_video_str and len(str(bg_video_str)) > 100:
                         final_data_uri = f"data:video/mp4;base64,{bg_video_str}"
                         return JSONResponse({"url": final_data_uri, "type": "data_uri"})
                    
                    # If we are here, we expected R2 upload but maybe verified details are missing?
                    # If view_url was generated, we returned it above.
                    
                    return JSONResponse({"output": output_data, "type": "raw"})

                elif status == "FAILED":
                    error_msg = status_data.get("error", "Unknown error")
                    print(f"RunPod Task Failed: {error_msg}")
                    raise HTTPException(status_code=502, detail=f"RunPod Processing Failed: {error_msg}")
                    
            except httpx.RequestError as e:
                print(f"Polling Error: {e}")
                # Retry logic could be added here
                raise HTTPException(status_code=502, detail="Error polling RunPod status")
    
    return HTTPException(status_code=500, detail="Unknown error flow")

@app.get("/api/upload-url")
def get_upload_url(filename: str, content_type: str = "video/mp4"):
    """
    Get a presigned URL to upload a file directly to the Cloud Hub.
    """
    # Create a unique key (folder/filename)
    object_name = f"uploads/{filename}"
    
    url = storage_manager.generate_presigned_upload_url(object_name)
    
    if not url:
        raise HTTPException(status_code=500, detail="Could not generate upload URL")
        
    return {"url": url, "key": object_name}

@app.get("/api/download-url")
def get_download_url(file_key: str):
    """
    Get a presigned URL to download a processed file.
    """
    url = storage_manager.generate_presigned_download_url(file_key)
    if not url:
        raise HTTPException(status_code=404, detail="File not found or error generating URL")
        
    return {"url": url}


@app.get("/api/debug-env")
def debug_env():
    """Debug endpoint to check if environment variables are loaded correctly"""
    key = os.getenv("RUNPOD_API_KEY", "")
    r2_url = os.getenv("R2_ENDPOINT_URL", "")
    
    return {
        "runpod_key_loaded": bool(key),
        "runpod_key_prefix": key[:10] + "..." if key else "None",
        "runpod_key_length": len(key),
        "r2_url_loaded": bool(r2_url),
        "r2_url_value": r2_url
    }

if __name__ == "__main__":
    uvicorn.run("api.index:app", host="0.0.0.0", port=8000, reload=True)
