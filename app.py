import os
import re
import random
import string
import cv2
import yt_dlp as youtube_dl
import shutil
import json
import time
import logging
import urllib.parse  # For URL encoding
from flask import Flask, render_template, request, send_file, jsonify, Response
from werkzeug.utils import safe_join

app = Flask(__name__)

# Global variable to keep track of processing status
processing_status = {
    'status': 'Idle',
    'step': '',
    'file': '',
    'progress': 0
}

def sanitize_title(title):
    sanitized_title = re.sub(r'[<>:"/\\|?*-]', '', title)
    sanitized_title = re.sub(r'\s+', ' ', sanitized_title).strip()
    return sanitized_title

def extract_frames(video_path, output_folder, interval_ms):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.error("Error: Could not open video.")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        logging.error("Error: Invalid FPS value.")
        return False

    interval_frames = int(fps * (interval_ms / 1000.0))
    frame_count = 0
    saved_frame_count = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % interval_frames == 0:
            frame_filename = os.path.join(output_folder, f"frame_{saved_frame_count:04d}.jpg")
            cv2.imwrite(frame_filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            saved_frame_count += 1

        frame_count += 1
        # Update progress
        processing_status['progress'] = int((frame_count / total_frames) * 100)

    cap.release()
    logging.info(f"Finished extracting frames. Total frames saved: {saved_frame_count}")
    return True

def download_youtube_video(url, output_path):
    try:
        # Path to your exported cookies file
        cookie_file = '/home/een/Documents/cookies.txt'
        
        with youtube_dl.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            original_title = info_dict['title']
            sanitized_title = sanitize_title(original_title)
            
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': os.path.join(output_path, f'{sanitized_title}.%(ext)s'),
                'merge_output_format': 'mp4',
                'noplaylist': True,
                'cookiefile': cookie_file  # Add cookiefile for authentication
            }
            
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            video_path = os.path.join(output_path, f"{sanitized_title}.mp4")
            return video_path, sanitized_title
    except Exception as e:
        logging.error(f"Error downloading video: {e}")
        return None, None


def zip_folder(folder_path):
    zip_filename = f"{folder_path}.zip"
    shutil.make_archive(folder_path, 'zip', folder_path)
    logging.info(f"Created zip archive: {zip_filename}")

def generate_random_name(extension="jpg"):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8)) + f".{extension}"
    
def rename_files_in_folder(folder_path):
    if not os.path.isdir(folder_path):
        logging.error(f"Error: The folder {folder_path} does not exist.")
        return

    for file_name in os.listdir(folder_path):
        old_file_path = os.path.join(folder_path, file_name)
        if os.path.isdir(old_file_path):
            continue

        new_file_name = generate_random_name(extension="jpg")
        new_file_path = os.path.join(folder_path, new_file_name)
        os.rename(old_file_path, new_file_path)

    logging.info(f"Files in {folder_path} renamed with random names successfully.")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_video():
    global processing_status
    processing_status['status'] = 'Processing'
    processing_status['step'] = 'Downloading Video'
    processing_status['progress'] = 0

    youtube_url = request.form['url']
    download_path = '/home/een/Downloads/YT-Downloads/AV_files'
    frame_download_path = '/home/een/Downloads/YT-Downloads/Extracts'
    sanitized_title = None
    video_path = None

    try:
        # Step 1: Download video
        processing_status['step'] = 'Downloading Video'
        processing_status['progress'] = 10
        video_path, sanitized_title = download_youtube_video(youtube_url, download_path)
        if not video_path or not os.path.exists(video_path):
            processing_status['status'] = 'Failed'
            return "Video download failed or file not found."

        # Step 2: Extract frames
        processing_status['step'] = 'Extracting Frames'
        processing_status['progress'] = 30
        output_folder = os.path.join(frame_download_path, sanitized_title)
        if not extract_frames(video_path, output_folder, 500):
            processing_status['status'] = 'Failed'
            return "Frame extraction failed."

        # Step 3: Rename frames with random names
        processing_status['step'] = 'Renaming Files'
        processing_status['progress'] = 50
        rename_files_in_folder(output_folder)

        # Step 4: Create ZIP archive
        processing_status['step'] = 'Creating ZIP Archive'
        processing_status['progress'] = 70
        zip_folder(output_folder)

        # Step 5: Clean up and finish
        processing_status['step'] = 'Cleaning Up'
        processing_status['progress'] = 90
        os.remove(video_path)
        shutil.rmtree(output_folder)

        # Final step
        processing_status['status'] = 'Completed'
        processing_status['step'] = 'Done'
        processing_status['progress'] = 100
        processing_status['file'] = f"{sanitized_title}.zip"

        safe_filename = urllib.parse.quote(processing_status['file'])
        return render_template('status.html', zip_filename=safe_filename)

    except Exception as e:
        processing_status['status'] = 'Failed'
        processing_status['step'] = 'Error'
        logging.error(f"Unexpected error: {e}")
        return "An unexpected error occurred."


@app.route('/status')
def status():
    return jsonify(processing_status)

@app.route('/progress')
def progress():
    def generate():
        while True:
            with app.app_context():
                yield f"data: {json.dumps(processing_status)}\n\n"
            time.sleep(1)  # Real-time update every 1 second
    return Response(generate(), mimetype='text/event-stream')


@app.route('/download/<filename>')
def download_file(filename):
    try:
        # Safe join to ensure the file path is safe and correctly handled
        file_path = safe_join('/home/een/Downloads/YT-Downloads/Extracts', filename)
        return send_file(file_path, as_attachment=True)
    except FileNotFoundError:
        return "File not found.", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
