import cv2
from argparse import ArgumentParser

from gimbal import Gimbal
from isource import ISource
from time import sleep


def main():
    parser = ArgumentParser(description='Camera auto aimer')
    parser.add_argument('-g', action='store_true', help='Run with GUI')
    args = parser.parse_args()

    ISource.list_devices()

    src = ISource()
    src.set_format(1920, 1080, 30, fmt='BGRx')

    src.camera.set_tcam_property("Exposure Auto", False)
    src.camera.set_tcam_property("Gain Auto", False)

    src.camera.set_tcam_property("Exposure", 3000)
    src.camera.set_tcam_property("Zoom", 0)
    src.play()
    print('Play started')

    gimbal = Gimbal('/dev/ttyUSB0', baudrate=115200, timeout=10)
    gimbal.motors_on()

    idx = 0

    def go(r, p, y):
        nonlocal idx
        gimbal.control_angle(r, p, y)
        image = None
        while image is None:
            sleep(0.6)
            image = src.read()
        if args.g:
            cv2.imshow('Image', image)
            cv2.waitKey()
        else:
            idx += 1
            cv2.imwrite(f'img_{idx:03}.png', image)

    go(0, 0, 0)
    go(0, -30, 0)
    go(0, -30, 30)
    go(0, 30, 30)
    go(0, 30, -30)
    go(0, 0, -30)
    go(0, 0, 0)
    go(0, -15, 0)
    go(0, -30, 0)
    go(0, -45, 0)
    go(0, -60, 0)
    gimbal.motors_off()


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()
