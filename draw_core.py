import os
import numpy as np
import cv2
from PIL import Image


def _imread_any(path):
    """pil -> cv2"""
    try:
        img = Image.open(path).convert("RGB")
        return np.array(img)[:, :, ::-1]  # to BGR for cv2
    except Exception:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"cannot identify image file '{path}'")
        return img  # BGR


def preprocess_image(path, target_w, target_h, blur=2,
                     use_canny=True, canny_low=60, canny_high=120,
                     morph_close=True, try_skeleton=True):
    """
    แปลงภาพ → หน้าจอขนาด target_w x target_h (letterbox)
    แล้วสร้าง mask เส้นสีขาวบนพื้นดำ (255 = เส้นที่จะวาด)
    - use_canny: ใช้ edge detection (คมและละเอียด)
    - blur: 0..31 (ค่าคี่) — 2–3 แนะนำ
    - try_skeleton: ถ้ามี opencv-contrib จะทำเส้นให้บาง 1px
    """
    img_bgr = _imread_any(path)


    ih, iw = img_bgr.shape[:2]
    scale = min(target_w / iw, target_h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    ox, oy = (target_w - nw) // 2, (target_h - nh) // 2
    canvas[oy:oy+nh, ox:ox+nw] = resized

    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)

    if blur and blur > 0:
        k = blur | 1 
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    if use_canny:
        edges = cv2.Canny(gray, canny_low, canny_high)
        if morph_close:
            edges = cv2.morphologyEx(
                edges, cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
                iterations=1
            )
        mask = edges
    else:
        # threshold ธรรมดา (เผื่ออยากลอง)
        th = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)[1]
        mask = th


    if try_skeleton:
        try:
            mask = cv2.ximgproc.thinning(mask) 
        except Exception:
            pass


    mask = (mask > 0).astype(np.uint8) * 255
    return mask


def extract_contours(mask, min_area=20):
    """
    x,y
    """
    cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cnts:
        if cv2.contourArea(c) >= float(min_area):
            pts = c.reshape(-1, 2)
            out.append(pts)
    out.sort(key=lambda p: -len(p))
    return out




def sample_points(contour, step=1):
    """
     step=1 = ละเอียดสุด
    """
    if step < 1:
        step = 1
    pts = contour[::step].astype(int)

    if len(pts) > 1:
        dedup = [pts[0]]
        for p in pts[1:]:
            if (abs(p[0] - dedup[-1][0]) + abs(p[1] - dedup[-1][1])) > 0:
                dedup.append(p)
        pts = np.array(dedup, dtype=int)
    return pts


# command generat

def _dist2(p, q):
    dx = int(p[0]) - int(q[0])
    dy = int(p[1]) - int(q[1])
    return dx*dx + dy*dy

def generate_swipe_commands(points, seg_ms=35, tap_thresh2=4):
    """
    แปลง polyline → ชุด ADB swipe
    """
    cmds = []
    if points is None or len(points) < 2:
        return cmds

    x0, y0 = map(int, points[0])

    cmds.append(f"input tap {x0} {y0}")

    for i in range(1, len(points)):
        x1, y1 = map(int, points[i-1])
        x2, y2 = map(int, points[i])
        if _dist2((x1, y1), (x2, y2)) <= tap_thresh2:
            cmds.append(f"input tap {x2} {y2}")
        else:
            cmds.append(f"input swipe {x1} {y1} {x2} {y2} {int(seg_ms)}")

    return cmds




def make_preview(mask):
    """
    building preview BGR to show GUI
    """
    if mask.ndim == 2:
        bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    else:
        bgr = mask.copy()
   
    bg = np.zeros_like(bgr)
    bg[:] = (24, 24, 28)
    fg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    fg[np.where(mask == 0)] = (0, 0, 0)
    out = cv2.add(bg, fg)
    return out

