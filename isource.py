from typing import NamedTuple, List, Any
from threading import Lock
from time import sleep
import cv2
import numpy as np
import sys
import gi

gi.require_version("Tcam", "0.1")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import Tcam, Gst, GstVideo


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


framecount = 0


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
        self.zoom = 0
        self.serial = serial
        self.buffer = None
        self.lock = Lock()
        self.properties = {}
        self.pipeline = Gst.parse_launch("tcambin name=source"
                                         " ! capsfilter name=filter"
                                         " ! videoconvert"
                                         " ! appsink name=sink")
        # test for error
        if not self.pipeline:
            raise RuntimeError("Could not create pipeline.")

        self.camera = self.pipeline.get_by_name("source")
        # The user has not given a serial, so we prompt for one
        if serial is not None:
            self.camera.set_property("serial", serial)

        property_names = self.camera.get_tcam_property_names()

        for name in property_names:
            params = list(self.camera.get_tcam_property(name))
            ret = params.pop(0)
            info = PropertyInfo(*params)

            if not ret:
                print("could not receive value {}".format(name))
                continue

            prop_type = prop_types.get(info.type, None)
            if prop_type is None:
                print(f'Property {name}: unknown type: {info.type}')
                continue

            prop = prop_type(name, self.camera, info)
            self.properties[name] = prop

    def set_format(self, width: int, height: int, fps: int, fmt='BGRx'):
        caps = Gst.Caps.new_empty()
        structure = Gst.Structure.new_from_string("video/x-raw")
        structure.set_value("width", width)
        structure.set_value("height", height)
        try:
            fraction = Gst.Fraction(fps, 1)
            structure.set_value("framerate", fraction)
        except TypeError:
            struc_string = structure.to_string()
            struc_string += ",framerate={}/{}".format(30, 1)
            structure.free()
            structure, end = structure.from_string(struc_string)

        caps.append_structure(structure)
        structure.free()
        caps_filter = self.pipeline.get_by_name("filter")
        if not caps_filter:
            print("Could not retrieve capsfilter from pipeline.")
            return 1
        caps_filter.set_property("caps", caps)

    def print_formats(self):
        self.camera.set_state(Gst.State.READY)
        caps = self.camera.get_static_pad("src").query_caps()
        for x in range(caps.get_size()):
            structure = caps.get_structure(x)
            name = structure.get_name()
            try:
                fmt = structure.get_value("format")

                if type(fmt) is str:
                    print("{} {}".format(name, fmt), end="")
                elif type(fmt) is Gst.ValueList:

                    print("{} {{ ".format(name), end="")

                    for y in range(Gst.ValueList.get_size(fmt)):
                        val = Gst.ValueList.get_value(fmt, y)

                        print("{} ".format(val), end="")
                    print("}", end="")
                else:
                    print("==")
            except TypeError:  # Gst.ValueList

                # this means we have multiple formats that all
                # have the same width/height/framerate settings

                begin = structure.to_string().find("format=(string){")
                substr = structure.to_string()[begin:]
                values = substr[substr.find("{") + 1:substr.find("}")]

                print("{} {{ ".format(name), end="")

                for fmt in values.split(","):
                    print("{} ".format(fmt), end="")

                print("}", end="")
                # continue

            # the python gobject introspection wrapper
            # can pose problems in older version
            # the type Gst.IntRange
            # may not be available and thus cause a TypeError
            # in such a case we query the string description
            # of the Gst.Structure and extract the framerates
            try:
                if structure.to_string().find("[") != -1:
                    raise TypeError

                width = structure.get_value("width")
                height = structure.get_value("height")

                print(" - {}x{} - ".format(width, height), end="")

            except TypeError:

                import re

                # width handling

                begin = structure.to_string().find("width=(int)[")
                substr = structure.to_string()[begin:]
                values = substr[substr.find("[") + 1:substr.find("]")]
                v = re.findall(r'\d+', values)

                # assume first entry is smaller
                width_min = v[0]
                width_max = v[1]

                # height handling

                begin = structure.to_string().find("height=(int)[")
                substr = structure.to_string()[begin:]
                values = substr[substr.find("[") + 1:substr.find("]")]
                v = re.findall(r'\d+', values)

                height_min = v[0]
                height_max = v[1]

                print(" - {}x{} <=> {}x{} - ".format(width_min, height_min, width_max, height_max), end="")

            # the python gobject introspection wrapper
            # can pose problems in older version
            # the types Gst.Fraction and Gst.FractionRange
            # may not be available and thus cause a TypeError
            # in such a case we query the string description
            # of the Gst.Structure and extract the framerates
            try:
                framerates = structure.get_value("framerate")
            except TypeError:

                import re

                substr = structure.to_string()[structure.to_string().find("framerate="):]

                try:
                    # try for frame rate lists
                    field, values, remain = re.split("{|}", substr, maxsplit=3)
                    rates = [x.strip() for x in values.split(",")]
                    for r in rates:
                        print("{} ".format(r), end="")
                except ValueError:  # we have a GstFractionRange

                    values = substr[substr.find("[") + 1:substr.find("]")]
                    v = re.findall(r'\d+', values)
                    fps_min_num = v[0]
                    fps_min_den = v[1]
                    fps_max_num = v[2]
                    fps_max_den = v[3]
                    # framerates are fractions thus one framerate euqals two values
                    print("{}/ {} <=> {}/{}".format(fps_min_num, fps_min_den,
                                                    fps_max_num, fps_max_den, end=""))

                # printf line break
                print("")
                # we are done here
                continue

            if type(framerates) is Gst.ValueList:

                for y in range(Gst.ValueList.get_size(framerates)):
                    val = Gst.ValueList.get_value(framerates, y)

                    print("{} ".format(val), end="")

            elif type(framerates) is Gst.FractionRange:

                min_val = Gst.value_get_fraction_range_min(framerates)
                max_val = Gst.value_get_fraction_range_max(framerates)
                print("{} <-> {}".format(min_val, max_val))

            else:
                print("framerates not supported {}".format(type(framerates)))
                # we are finished
            print("")

    @staticmethod
    def callback(app_sink, obj: 'ISource'):
        """
        This function will be called in a separate thread when our appsink
        says there is data for us. user_data has to be defined
        when calling g_signal_connect. It can be used to pass objects etc.
        from your other function to the callback.
        """
        sample = app_sink.emit("pull-sample")
        if sample:
            caps = sample.get_caps()
            gst_buffer = sample.get_buffer()
            try:
                (ret, buffer_map) = gst_buffer.map(Gst.MapFlags.READ)
                video_info = GstVideo.VideoInfo()
                video_info.from_caps(caps)

                np_data = np.frombuffer(buffer_map.data, np.uint8).reshape((video_info.height, video_info.width, 3))
                with obj.lock:
                    buffer = obj.buffer
                    if buffer is None or buffer.shape != np_data.shape:
                        obj.buffer = np_data.copy()
                    else:
                        np.copyto(buffer, np_data)
            finally:
                gst_buffer.unmap(buffer_map)

        return Gst.FlowReturn.OK

    def play(self):
        sink = self.pipeline.get_by_name("sink")
        # tell appsink to notify us when it receives an image
        sink.set_property("emit-signals", True)
        sink.connect("new-sample", self.callback, self)
        self.pipeline.set_state(Gst.State.PLAYING)

    def read(self):
        with self.lock:
            return self.buffer.copy() if self.buffer is not None else None


if __name__ == "__main__":
    devs = ISource.list_devices()
    src = ISource()
    src.print_formats()
    src.set_format(1920, 1080, 30, fmt='BGRx')

    src.camera.set_tcam_property("Exposure Auto", False)
    src.camera.set_tcam_property("Gain Auto", False)

    src.camera.set_tcam_property("Exposure", 3000)
    src.camera.set_tcam_property("Zoom", 0)
    src.play()
    # src.set_format(640, 480, 30, fmt='BGRx')
    while True:
        image = src.read()
        if image is not None:
            cv2.imshow('data', image)
            k = cv2.waitKey(20)
            if k == ord('='):
                src.zoom += 1
                src.camera.set_tcam_property("Zoom", src.zoom)
            elif k == ord('-'):
                src.zoom -= 1
                src.camera.set_tcam_property("Zoom", src.zoom)
