import os
import base64
import time
import requests
import uuid
import logging
import runpod
from src.model_loader import load_model
from src.inference import process_video

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
MODEL_PATH = os.environ.get("MODEL_PATH", "/workspace/model_weights")
DEVICE = "cuda"
USE_FP8 = os.environ.get("USE_FP8", "true").lower() == "true"

# Global Model Cache
model = None

def init_model():
    global model
    if model is None:
        logger.info("Initializing model...")
        try:
            model = load_model(MODEL_PATH, device=DEVICE, use_fp8=USE_FP8)
            logger.info("Model initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to init model: {e}")
            raise e

def download_file(url, local_path):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def decode_base64(b64_string, local_path):
    with open(local_path, "wb") as f:
        f.write(base64.b64decode(b64_string))

def encode_file_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')

def upload_file_to_presigned_url(local_path, upload_url):
    """
    Uploads the file at local_path to the given presigned URL using HTTP PUT.
    """
    try:
        logger.info(f"Uploading output to presigned URL: {upload_url[:50]}...")
        with open(local_path, 'rb') as f:
            response = requests.put(upload_url, data=f)
            response.raise_for_status()
        logger.info("Upload successful.")
        return True
    except Exception as e:
        logger.error(f"Failed to upload to presigned URL: {e}")
        raise e

def handler(event):
    global model
    
    # 1. Parse Input
    job_input = event.get("input", {})
    video_source = job_input.get("video")
    # New: Accept a presigned URL to upload the result to
    output_upload_url = job_input.get("output_upload_url")
    
    target_width = job_input.get("target_width", 1920)
    target_height = job_input.get("target_height", 1080)
    quality = job_input.get("quality", "balanced")
    
    if not video_source:
        return {"error": "No video provided"}
        
    job_id = event.get("id", str(uuid.uuid4()))
    temp_dir = f"/tmp/{job_id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = os.path.join(temp_dir, "input.mp4")
    output_path = os.path.join(temp_dir, "output.mp4")
    
    start_time = time.time()
    
    try:
        # 2. Get Video
        if video_source.startswith("http"):
            download_file(video_source, input_path)
        else:
            # Assume base64
            decode_base64(video_source, input_path)
            
        # 3. Process
        process_video(
            model,
            input_path,
            output_path,
            target_resolution=(target_width, target_height),
            quality_mode=quality
        )
        
        processing_time = time.time() - start_time
        
        # 4. Return Output
        result = {
            "status": "success",
            "processing_time": processing_time,
            "metadata": {
                "output_resolution": f"{target_width}x{target_height}",
                "quality_mode": quality
            }
        }

        # Optimization: If Upload URL is provided, upload there and don't return Base64
        if output_upload_url:
            upload_file_to_presigned_url(output_path, output_upload_url)
            result["message"] = "Output uploaded to provided URL"
        else:
            # Fallback for backward compatibility (small files)
            logger.warning("No output_upload_url provided. Returning Base64 (Might fail for large files).")
            output_b64 = encode_file_to_base64(output_path)
            result["output_video"] = output_b64
        
        return result

    except Exception as e:
        logger.error(f"Handler error: {e}")
        return {"status": "error", "message": str(e)}
        
    finally:
        # Cleanup
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    # Cold start
    init_model()
    runpod.serverless.start({"handler": handler})
