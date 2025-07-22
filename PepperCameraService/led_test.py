import qi
import time

session = qi.Session()
session.connect("tcp://127.0.0.1:9559")
led_controller = session.service("ALLeds")
print("dzik")

while True:
    led_controller.off("AllLeds")
    led_controller.on("AllLedsRed")
    time.sleep(1)
    led_controller.off("AllLeds")
    led_controller.on("AllLedsBlue")
    time.sleep(1)

