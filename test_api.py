import subprocess
import time
import urllib.request
import urllib.error
import sys
import os

def test_api():
    exe_path = os.path.normpath(os.path.join(os.getcwd(), 'dist', 'AvocadoStream.exe'))
    print(f"Starting process: {exe_path}")
    
    # Start the executable
    p = subprocess.Popen([exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("Process started, sleeping 4 seconds...")
    time.sleep(4)
    
    # Query the API
    url = "http://localhost:8000/api/torrent/search?query=Ashita+no+Joe+2"
    print(f"Requesting: {url}")
    
    success = False
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode('utf-8')
            print(f"Response status: {response.status}")
            print(f"Response body (first 1000 chars): {content[:1000]}")
            success = True
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}")
    except Exception as e:
        print(f"General Error: {e}")
        
    # Terminate the process
    print("Terminating process...")
    p.terminate()
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        print("Force killing...")
        p.kill()
    print("Process terminated.")
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    test_api()
