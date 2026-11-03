"""Cuts the car seat clip the simulator plays from the Oct 31 glasses kit take. The take is a local file and the clip stays out of git.

Run: python3 scripts/simulator_media.py SOURCE.mp4 data-sim/media/carseat.mp4
The ask, then the twist card with the coach's twist line, then the last card with its advice. Captions: simulator/static/carseat.*.vtt.
"""
import subprocess
import sys

CROP = "crop=384:384:170:314,fps=24,setsar=1"
# video start, audio start, seconds. The twist card comes before its spoken line in the take, so the middle part pairs them.
PARTS = ((7.2, 7.2, 3.4), (85.0, 103.7, 8.9), (165.4, 165.4, 7.6))


def main(source, out):
    chain, labels = [], ""
    for i, (video, audio, seconds) in enumerate(PARTS):
        chain.append(f"[0:v]trim=start={video}:duration={seconds},setpts=PTS-STARTPTS,{CROP}[v{i}]")
        chain.append(f"[0:a]atrim=start={audio}:duration={seconds},asetpts=PTS-STARTPTS[a{i}]")
        labels += f"[v{i}][a{i}]"
    chain.append(f"{labels}concat=n={len(PARTS)}:v=1:a=1[v][a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", source, "-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out], check=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
