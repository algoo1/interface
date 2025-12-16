import requests
import base64
import time
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
VIDEO_PATH = r"c:\Users\Doctor Laptop\Desktop\مم\03.mp4"
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
RUNPOD_ENDPOINT_ID = "hgn3kb2km6tnxi"
RUNPOD_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run"
RUNPOD_STATUS_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status"

HEADERS = {
    "Authorization": f"Bearer {RUNPOD_API_KEY}",
    "Content-Type": "application/json"
}

def test_runpod():
    if not os.path.exists(VIDEO_PATH):
        print(f"Error: Video file not found at {VIDEO_PATH}")
        return

    print(f"Reading video file: {VIDEO_PATH}")
    with open(VIDEO_PATH, "rb") as f:
        video_bytes = f.read()
    
    video_base64 = base64.b64encode(video_bytes).decode('utf-8')
    print(f"Video encoded. Size: {len(video_base64) / 1024 / 1024:.2f} MB")

    payload = {
        "input": {
            "video": video_base64
        }
    }

    print("Sending request to RunPod...")
    try:
        response = requests.post(RUNPOD_URL, headers=HEADERS, json=payload, timeout=600)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")

        if response.status_code != 200:
            print("Request Failed!")
            return

        data = response.json()
        request_id = data.get("id")
        print(f"Request ID: {request_id}")

        # Polling
        while True:
            time.sleep(2)
            status_resp = requests.get(f"{RUNPOD_STATUS_URL}/{request_id}", headers=HEADERS)
            status_data = status_resp.json()
            status = status_data.get("status")
            print(f"Status: {status}")

            if status == "COMPLETED":
                print("Processing Complete!")
                output = status_data.get("output")
                print("Output received (truncated):", str(output)[:200])
                break
            elif status == "FAILED":
                print("Processing Failed!")
                print("Error:", status_data.get("error"))
                break
    
    except Exception as e:
        print(f"Exception occurred: {e}")

if __name__ == "__main__":
    test_runpod()
