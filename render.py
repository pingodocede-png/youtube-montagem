import os, json, base64, subprocess, urllib.request, shutil

job = json.loads(base64.b64decode(os.environ["JOB"]).decode("utf-8"))
fmt = job.get("format", "short")
W, H = (1080, 1920) if fmt == "short" else (1920, 1080)
os.makedirs("work", exist_ok=True)
os.makedirs("out", exist_ok=True)


def dl(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def run(cmd):
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def ts(t):
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# 1. Narracao
dl(job["audio_url"], "work/audio.wav")
total = probe("work/audio.wav")

# 2. Duracao de cada cena proporcional ao texto narrado
scenes = job["scenes"]
weights = [max(len(s.get("narration", "")), 1) for s in scenes]
sw = sum(weights)
durs = [total * w / sw for w in weights]

# 3. Cortar/ajustar cada clip ao formato (vertical nos Shorts) e a duracao da cena
vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,setsar=1,format=yuv420p"
parts = []
for i, (s, d) in enumerate(zip(scenes, durs)):
    src, out = f"work/clip{i}.mp4", f"work/part{i}.mp4"
    ok = False
    if s.get("video_url"):
        try:
            dl(s["video_url"], src)
            run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, "-t", f"{d:.3f}", "-vf", vf, "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", out])
            ok = True
        except Exception as e:
            print("Clip falhou, uso fundo preto:", i, e, flush=True)
    if not ok:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=30", "-t", f"{d:.3f}",
             "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out])
    parts.append(out)

with open("work/list.txt", "w") as f:
    for p in parts:
        f.write(f"file '{os.path.basename(p)}'\n")
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/list.txt", "-c", "copy", "work/video.mp4"])

# 4. Legendas sincronizadas com a narracao (blocos curtos de palavras)
k = 4 if fmt == "short" else 7
lines, t, n = [], 0.0, 1
for s, d in zip(scenes, durs):
    words = s.get("narration", "").split()
    chunks = [" ".join(words[j:j + k]) for j in range(0, len(words), k)] or [""]
    cw = [max(len(c), 1) for c in chunks]
    tot, st = sum(cw), t
    for c, w in zip(chunks, cw):
        dd = d * w / tot
        if c:
            lines.append(f"{n}\n{ts(st)} --> {ts(st + dd)}\n{c}\n")
            n += 1
        st += dd
    t += d
with open("work/subs.srt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

if fmt == "short":
    style = "FontName=DejaVu Sans,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=70"
else:
    style = "FontName=DejaVu Sans,FontSize=11,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=18"

# 5. Juntar video + voz + legendas
name = f"{job['concept_id']}-{job['language']}-{fmt}.mp4"
run(["ffmpeg", "-y", "-i", "work/video.mp4", "-i", "work/audio.wav",
     "-vf", f"subtitles=work/subs.srt:force_style='{style}'",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
     "-shortest", "-movflags", "+faststart", f"out/{name}"])

with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
    f.write(f"file={name}\n")
    f.write(f"duration={round(total, 2)}\n")
print("Pronto:", name, flush=True)
