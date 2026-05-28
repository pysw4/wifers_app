import keras_ocr
import easyocr
import matplotlib.pyplot as plt
import glob
import cv2

path = "./iloveimg-converted/*.jpg"

image_paths = sorted(glob.glob(path))
img = [cv2.imread(p) for p in image_paths if cv2.imread(p) is not None]

print(f"Number of images loaded: {len(img)}")

reader = easyocr.Reader(['en'], gpu = True)
pipeline = keras_ocr.pipeline.Pipeline()
print("Models loaded successfully.")

# -------------- MODELS --------------
res_keras = pipeline.recognize(img[:10])
for img, text in zip(res_keras, img[:10]):
    print(text)
print("Keras OCR results obtained.")

res_easy = []
for img in img[:10]:
    result = reader.readtext(img)
    res_easy.append(result)
print("Easy OCR results obtained.")

# -------------- RESULTS --------------
for i in range(10):
    fig, axs = plt.subplots(1, 2, figsize=(15, 10))
    keras_ocr.tools.drawAnnotations(plt.imread(img[i]), res_keras[i], ax=axs[0])
    axs[0].set_title('Keras OCR Result')
    plt.show()

    keras_ocr.tools.drawAnnotations(plt.imread(img[i]), res_easy[i], ax=axs[1])
    axs[1].set_title('Easy OCR Result')
    plt.show()