from typing import NamedTuple, List, Any
from multiprocessing import Process
from time import sleep
import cv2
import numpy as np
import sys
import gi


class DeviceInfo(NamedTuple):
    model: str
    serial: str
    identifier: str
    type: str


class PropertyInfo(NamedTuple):
    value: Any
    min_value: Any
    max_value: Any
    default_value: Any
    step_size: Any
    type: str
    flags: int
    category: str
    group: str


gi.require_version("Tcam", "0.1")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import Tcam, Gst, GstVideo

framecount = 0


def callback(appsink, user_data):
    """
    This function will be called in a separate thread when our appsink
    says there is data for us. user_data has to be defined
    when calling g_signal_connect. It can be used to pass objects etc.
    from your other function to the callback.
    """
    sample = appsink.emit("pull-sample")

    if sample:

        caps = sample.get_caps()

        gst_buffer = sample.get_buffer()

        try:
            (ret, buffer_map) = gst_buffer.map(Gst.MapFlags.READ)

            video_info = GstVideo.VideoInfo()
            video_info.from_caps(caps)

            stride = video_info.finfo.bits / 8

            pixel_offset = int(video_info.width / 2 * stride +
                               video_info.width * video_info.height / 2 * stride)

            np_data = np.frombuffer(buffer_map.data, np.uint8).reshape((video_info.height, video_info.width, 3))
            cv2.imshow('data', np_data)
            cv2.waitKey(1)
            print('np shape:', np_data.shape)

            pixel_data = buffer_map.data[pixel_offset]
            #print('Type of buffer_map.data:', type(buffer_map.data), 'len: ', len(buffer_map.data))
            timestamp = gst_buffer.pts

            global framecount

            output_str = "Captured frame {}, Pixel Value={} Timestamp={}".format(framecount,
                                                                                 pixel_data,
                                                                                 timestamp)

            print(output_str, end="\r")  # print with \r to rewrite line

            framecount += 1

        finally:
            gst_buffer.unmap(buffer_map)

    return Gst.FlowReturn.OK


Gst.init(sys.argv)  # init gstreamer


class NumProperty:
    def __init__(self, name, camera, info: PropertyInfo):
        self.name = name
        self.camera = camera
        self.info = info


class EnumProperty:
    def __init__(self, name, camera, info: PropertyInfo):
        self.name = name
        self.camera = camera
        ...


prop_types = {
    'integer': NumProperty,
    'double': NumProperty,
    'enum': EnumProperty,
}


class ISource:
    @staticmethod
    def list_devices(print_list=True) -> List[DeviceInfo]:
        """
        Print information about all  available devices
        """
        result = []
        source = Gst.ElementFactory.make("tcambin")
        serials = source.get_device_serials()
        for serial in serials:
            flag, model, identifier, connection_type = source.get_device_info(serial)
            if flag:
                result.append(DeviceInfo(model, serial, identifier, connection_type))
                if print_list:
                    print(f'Model: {model} Serial: {serial} Type: {connection_type}')
        return result

    def __init__(self, serial=None):
        self.serial = serial
        self.properties = {}
        camera = Gst.ElementFactory.make("tcambin")
        if serial is not None:
            camera.set_property("serial", serial)
        property_names = camera.get_tcam_property_names()

        for name in property_names:
            params = list(camera.get_tcam_property(name))
            ret = params.pop(0)
            info = PropertyInfo(*params)

            if not ret:
                print("could not receive value {}".format(name))
                continue

            prop_type = prop_types.get(info.type, None)
            if prop_type is None:
                print(f'Property {name}: unknown type: {info.type}')
                continue

            prop = prop_type(name, camera, info)
            self.properties[name] = prop

    @staticmethod
    def play_process(serial=None):
        print(f'Process started with serial {serial}')
        Gst.init(sys.argv)  # init gstreamer
        pipeline = Gst.parse_launch("tcambin name=source"
                                    " ! videoconvert"
                                    " ! appsink name=sink")
        # test for error
        if not pipeline:
            print("Could not create pipeline.")
            sys.exit(1)

        # The user has not given a serial, so we prompt for one
        if serial is not None:
            source = pipeline.get_by_name("source")
            source.set_property("serial", serial)

        sink = pipeline.get_by_name("sink")
        # tell appsink to notify us when it receives an image
        sink.set_property("emit-signals", True)

        user_data = "This is our user data"
        # tell appsink what function to call when it notifies us
        sink.connect("new-sample", callback, user_data)
        pipeline.set_state(Gst.State.PLAYING)
        print("Press Ctrl-C to stop.")
        # We wait with this thread until a
        # KeyboardInterrupt in the form of a Ctrl-C
        # arrives. This will cause the pipline
        # to be set to state NULL
        #try:
        #    while True:
        #        sleep(1)
        #except KeyboardInterrupt:
        #    pass
        #finally:
        #    pipeline.set_state(Gst.State.NULL)

    def read(self):
        # process = Process(target=self.play_process, args=(self.serial,))
        # process.start()
        self.play_process(self.serial)
        while True:
            sleep(1)
            ...


if __name__ == "__main__":
    devs = ISource.list_devices()
    src = ISource()
    src.read()
    print()