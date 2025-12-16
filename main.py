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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (frontend)
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

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
async def upscale_video(file: UploadFile = File(...)):
    print(f"Received file: {file.filename}")
    
    # 1. Read and Encode Video
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
            
        # Warning: loading whole video into memory. Good for prototypes, bad for production.
        video_base64 = base64.b64encode(content).decode('utf-8')
        print(f"Video encoded to base64. Size: {len(video_base64) / 1024 / 1024:.2f} MB")
        
        if len(video_base64) > 50 * 1024 * 1024:
             print("Warning: File size > 50MB. RunPod might reject this payload.")

    except Exception as e:
        print(f"Error reading/encoding file: {e}")
        raise HTTPException(status_code=500, detail="Failed to process video file")

    # 2. Send to RunPod
    payload = {
        "input": {
            "video": video_base64
        }
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT_SETTINGS) as client:
        try:
            print("Sending request to RunPod...")
            response = await client.post(RUNPOD_URL, headers=HEADERS, json=payload)
            
            if response.status_code != 200:
                print(f"RunPod Error Status: {response.status_code}")
                print(f"RunPod Error Body: {response.text}")
                raise HTTPException(status_code=502, detail=f"RunPod Error ({response.status_code}): {response.text[:200]}")
            
            try:
                data = response.json()
            except ValueError:
                 print(f"RunPod Non-JSON Response: {response.text}")
                 raise HTTPException(status_code=502, detail=f"RunPod returned invalid JSON: {response.text[:200]}")

            request_id = data.get("id")
            print(f"RunPod Request ID: {request_id}")
            
        except httpx.RequestError as e:
            print(f"RunPod Connection Error: {e}")
            raise HTTPException(status_code=502, detail=f"RunPod Connection Error: {str(e)}")

        # 3. Poll for Status
        status = "IN_PROGRESS"
        output_data = None
        
        while status in ["IN_PROGRESS", "IN_QUEUE"]:
            await asyncio.sleep(2)  # Non-blocking sleep
            try:
                status_resp = await client.get(f"{RUNPOD_STATUS_URL}/{request_id}", headers=HEADERS)
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status")
                print(f"Polling Status: {status}")
                
                if status == "COMPLETED":
                    output_data = status_data.get("output")
                elif status == "FAILED":
                    error_msg = status_data.get("error", "Unknown error")
                    print(f"RunPod Task Failed: {error_msg}")
                    raise HTTPException(status_code=502, detail=f"RunPod Processing Failed: {error_msg}")
                    
            except httpx.RequestError as e:
                print(f"Polling Error: {e}")
                # Retry logic could be added here
                raise HTTPException(status_code=502, detail="Error polling RunPod status")

    # 4. Process Output
    if not output_data:
        raise HTTPException(status_code=500, detail="No output received from RunPod")
        
    bg_video_str = None
    if isinstance(output_data, str):
        bg_video_str = output_data
    elif isinstance(output_data, dict):
        bg_video_str = output_data.get("video") or output_data.get("output_video") or output_data.get("base64")
        if not bg_video_str:
             # Maybe it returns a url?
             url_video = output_data.get("url")
             if url_video:
                 return JSONResponse({"url": url_video, "type": "url"})
        
    if bg_video_str and len(str(bg_video_str)) > 100:
        try:
            output_filename = f"upscaled_{file.filename}"
            output_path = os.path.join("static", output_filename)
            
            if "," in bg_video_str[:50]:
                bg_video_str = bg_video_str.split(",")[1]
                
            video_bytes = base64.b64decode(bg_video_str)
            async with aiofiles.open(output_path, 'wb') as out_file:
                await out_file.write(video_bytes)
                
            final_url = f"/{output_filename}"
            print(f"Saved output to {output_path}")
            
            return JSONResponse({"url": final_url, "type": "local"})

        except Exception as e:
            print(f"Error saving output video: {e}")
            raise HTTPException(status_code=500, detail="Failed to save upscaled video")
            
    else:
        print(f"Output data handling fallback: {output_data}")
        return JSONResponse({"output": output_data, "type": "raw"})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
