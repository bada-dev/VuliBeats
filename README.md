# VuliBeats

## No permission is granted to use, copy, modify, distribute, or reproduce this software or any part of it without explicit written permission from the author.

VuliBeats was originally made for personal reasons. It is a music player designed to download youtube music videos and play them on your phone for free, and offline.
It caches the music videos and transfers.

The python code to download the youtube videos I found online and is below:

```
import yt_dlp
import os

def download_playlist(playlist_url, output_path="downloads"):
    os.makedirs(output_path, exist_ok=True)
    
    ydl_opts = {
        'outtmpl': f'{output_path}/%(playlist_title)s/%(title)s.%(ext)s',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'ignoreerrors': True,
        'quiet': False,
        'no_warnings': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([playlist_url])
        print("download complete")
    except Exception as e:
        print(f"Huge error!11!!!!1!: {e}")

if __name__ == "__main__":
    url = input("Playlist URL: ")
    download_playlist(url)

```
The app (runs on website and median.co) does expect you to drop the files given by that program. However, for any case, it does also exept mp4 videos for example.
