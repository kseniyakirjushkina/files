import cv2
import numpy as np
import os
import random
from pathlib import Path
from PIL import Image
import mediapipe as mp


class SimpleSyntheticGenerator:
    def __init__(self):
        self.hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2,
                                              min_detection_confidence=0.5, min_tracking_confidence=0.4,
                                              model_complexity=1)

    def load_image(self, path):
        try:
            return cv2.cvtColor(np.array(Image.open(path).convert('RGB')), cv2.COLOR_RGB2BGR)
        except:
            return None

    def remove_background(self, watch_img):
        img = watch_img.copy()
        mask = cv2.bitwise_not(cv2.inRange(img, np.array([200, 200, 200]), np.array([255, 255, 255])))
        y, x = np.nonzero(mask)
        if len(y) > 0:
            w, h = x.max() - x.min(), y.max() - y.min()
        else:
            w, h = img.shape[1], img.shape[0]
        return cv2.merge([*cv2.split(img), mask]), mask, w, h

    def augment_watch_appearance(self, watch_rgba):
        img = watch_rgba[:, :, :3].copy()
        alpha = watch_rgba[:, :, 3]

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 0] = (hsv[:, :, 0] + random.uniform(-10, 10)) % 180
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * random.uniform(0.7, 1.3), 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * random.uniform(0.6, 1.4), 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        img = cv2.convertScaleAbs(img, alpha=random.uniform(0.8, 1.2), beta=random.randint(-30, 30))

        if random.random() < 0.25:
            k = random.choice([3, 5])
            img = cv2.GaussianBlur(img, (k, k), 0)

        if random.random() < 0.15:
            noise = np.random.normal(0, random.uniform(5, 12), img.shape).astype(np.int16)
            img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        return cv2.merge([img[:, :, 0], img[:, :, 1], img[:, :, 2], alpha])

    def detect_wrist(self, image):
        results = self.hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if not results.multi_hand_landmarks:
            return None

        h, w = image.shape[:2]
        wrists = []
        for hl in results.multi_hand_landmarks:
            lm = hl.landmark
            wx, wy = int(lm[0].x * w), int(lm[0].y * h) # запястье
            mx, my = lm[9].x * w, lm[9].y * h   # костяшка среднего пальца
            px, py = lm[17].x * w, lm[17].y * h # костяшка мизинца
            ix, iy = lm[5].x * w, lm[5].y * h   # костяшка указательного

            dx_arm, dy_arm = mx - wx, my - wy
            arm_angle = np.degrees(np.arctan2(dy_arm, dx_arm))

            hand_width = np.sqrt((ix - px) ** 2 + (iy - py) ** 2)
            hand_length = np.sqrt(dx_arm ** 2 + dy_arm ** 2)
            wrist_width = hand_width * 0.70

            if hand_length < 50 or hand_width < 30: continue

            rec_size = max(50, min(400, int(wrist_width * 1.5)))

            wrists.append({
                'position': (wx, wy),
                'angle': arm_angle,
                'recommended_watch_size': rec_size
            })

        return wrists if wrists else None

    def place_watch(self, hand_image, watch_rgba, wrist_info, watch_size=150, real_watch_size=None):
        watch_rgba = self.augment_watch_appearance(watch_rgba)
        
        wx, wy, h, w = wrist_info['position'][0], wrist_info['position'][1], watch_rgba.shape[0], watch_rgba.shape[1]
        
        scale = watch_size / real_watch_size if real_watch_size else watch_size / max(h, w)
        wr = cv2.resize(watch_rgba, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        c = (wr.shape[1] // 2, wr.shape[0] // 2)
        M = cv2.getRotationMatrix2D(c, wrist_info['angle'], 1.0)
        nw, nh = int(wr.shape[0] * abs(M[0, 1]) + wr.shape[1] * abs(M[0, 0])), int(
            wr.shape[0] * abs(M[0, 0]) + wr.shape[1] * abs(M[0, 1]))
        M[0, 2], M[1, 2] = M[0, 2] + nw / 2 - c[0], M[1, 2] + nh / 2 - c[1]
        wr = cv2.warpAffine(wr, M, (nw, nh)) # поворот

        fx, fy = wx + random.randint(-8, 8) - nw // 2, wy + random.randint(-8, 8) - nh // 2
        res, msk = hand_image.copy(), np.zeros(hand_image.shape[:2], np.uint8)
        y1, y2, x1, x2 = max(0, fy), min(res.shape[0], fy + nh), max(0, fx), min(res.shape[1], fx + nw)
        wy1, wy2, wx1, wx2 = max(0, -fy), max(0, -fy) + (y2 - y1), max(0, -fx), max(0, -fx) + (x2 - x1)

        if y2 > y1 and x2 > x1 and wr.shape[2] == 4:
            a = np.repeat(wr[wy1:wy2, wx1:wx2, 3:4] / 255.0, 3, axis=2)
            res[y1:y2, x1:x2] = (
                    wr[wy1:wy2, wx1:wx2, :3].astype(float) * a + res[y1:y2, x1:x2].astype(float) * (1 - a)).astype(
                np.uint8)
            msk[y1:y2, x1:x2] = (wr[wy1:wy2, wx1:wx2, 3] > 25).astype(np.uint8) * 255 # маска для YOLO
        return res, msk

    def generate_synthetic_dataset(self, folder, watches_folder, output_folder, num_watches=10, max_images=10):
        imgs_dir, masks_dir = os.path.join(output_folder, 'images'), os.path.join(output_folder, 'masks')
        os.makedirs(imgs_dir, exist_ok=True)
        os.makedirs(masks_dir, exist_ok=True)

        people = list(Path(folder).glob('*.*'))
        watches = list(Path(watches_folder).glob('*.jpg'))[:num_watches]
        cnt, attempts = 0, 0
        max_attempts = max_images * 10

        print(f"Дано: {len(people)} фотографий людей и {len(watches)} часов")

        watch_data = []
        for wf in watches:
            w_img = self.load_image(wf)
            if w_img is None: continue
            try:
                wrgba, _, nw, nh = self.remove_background(w_img)
                watch_data.append((wrgba, max(nw, nh)))
            except:
                continue

        print(f"Очищен фон у {len(watch_data)} часов.")
        print(f"Начало генерации.")

        while cnt < max_images and attempts < max_attempts:
            attempts += 1

            if not watch_data or not people:
                break

            wrgba, rsz = random.choice(watch_data)
            wmf = random.choice(people)

            wm = self.load_image(wmf)
            if wm is None: continue

            wrsts = self.detect_wrist(wm)
            if not wrsts: continue

            wr = wrsts[0]
            try:
                sz = int(wr['recommended_watch_size'] * random.uniform(0.9, 1.1))
                res, msk = self.place_watch(wm, wrgba, wr, sz, rsz)
                cv2.imwrite(os.path.join(imgs_dir, f'synthetic_{cnt:05d}.jpg'), res)
                cv2.imwrite(os.path.join(masks_dir, f'synthetic_{cnt:05d}.png'), msk)
                cnt += 1
                if cnt % 100 == 0: print(f"{cnt}/{max_images}")
            except:
                pass

        print(f"Готово: {cnt} изображений за {attempts} попыток")
        return cnt

    def __del__(self):
        if hasattr(self, 'hands'): self.hands.close()


if __name__ == "__main__":
    SimpleSyntheticGenerator().generate_synthetic_dataset(
        r"фото для синтетики\женщины",
        r"kagglehub\datasets\mathewkouch\a-dataset-of-watches\versions\6\watches\watches\images",
        r"synthetic_dataset0\women",
        num_watches=700,
        max_images=3000
    )

    SimpleSyntheticGenerator().generate_synthetic_dataset(
        r"фото для синтетики\мужчины",
        r"kagglehub\datasets\mathewkouch\a-dataset-of-watches\versions\6\watches\watches\images",
        r"synthetic_dataset0\men",
        num_watches=700,
        max_images=3000
    )
