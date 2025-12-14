# Copyright (C) 2005-2011 Francois Meyer (dulle at free.fr)
# Copyright (C) 2012-2025 team free-astro (see more in AUTHORS file)
# Reference site is https://siril.org
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Enums submodule for Siril. This submodule contains all the enums used
within sirilpy.
"""

from enum import IntEnum, unique


@unique
class STFType(IntEnum):
    """enum representing STF types"""

    LINEAR_DISPLAY = 0
    LOG_DISPLAY = 1
    SQRT_DISPLAY = 2
    SQUARED_DISPLAY = 3
    ASINH_DISPLAY = 4
    AUTOSTRETCH_DISPLAY = 5
    HISTEQ_DISPLAY = 6


@unique
class SlidersMode(IntEnum):
    MIPSLOHI = 0
    MINMAX = 1
    USER = 2


@unique
class ImageType(IntEnum):
    """enum representing image functional types"""

    UNKNOWN = 0
    LIGHT = 1
    DARK = 2
    FLAT = 3
    BIAS = 4


@unique
class _Status(IntEnum):
    """
    Returns the status of a command. NONE is for commands that
    may legitimately fail to return data but which should not be
    regarded as an error, instead this triggers the command processor
    to return the special python value None
    Internal class: this is not intended for use in scripts.
    """

    OK = 0
    NONE = 1
    ERROR = 0xFF


class SirilVport:
    """
    Defines the Siril viewports
    """

    RED = 0
    MONO = 0
    GREEN = 1
    BLUE = 2
    RGB = 3


@unique
class LogColor(IntEnum):
    """
    Defines colors available for use with ``SirilInterface.log()``
    For consistency ``LogColor.Default`` should be used for normal messages,
    ``LogColor.Red`` should be used for error messages, ``LogColor.Salmon``
    should be used for warning messages, LogColor.Green should  be used
    for completion notifications, and ``LogColor.Blue`` should be used for
    technical messages such as equations, coefficients etc.
    """

    DEFAULT = 0
    RED = 1
    SALMON = 2
    GREEN = 3
    BLUE = 4


@unique
class _Command(IntEnum):
    """
    Enumerates the commands. This enum MUST match the one in
    siril_pythonmodule.h. Internal class: this is not intended for
    use in scripts.
    """

    SEND_COMMAND = 1
    LOG_MESSAGE = 2
    UPDATE_PROGRESS = 3
    GET_WORKING_DIRECTORY = 4
    GET_FILENAME = 5
    GET_DIMENSIONS = 6
    GET_PIXELDATA = 7
    GET_PIXELDATA_REGION = 8
    RELEASE_SHM = 9
    SET_PIXELDATA = 10
    GET_IMAGE_STATS = 11
    GET_KEYWORDS = 12
    GET_ICC_PROFILE = 13
    GET_FITS_HEADER = 14
    GET_FITS_HISTORY = 15
    GET_FITS_UNKNOWN_KEYS = 16
    GET_IMAGE = 17
    GET_PSFSTARS = 18
    GET_SEQ_STATS = 19
    GET_SEQ_REGDATA = 20
    GET_SEQ_IMGDATA = 21
    GET_SEQ_PIXELDATA = 22
    GET_SEQ_IMAGE = 23
    GET_SEQ = 24
    GET_CONFIG = 25
    GET_USERCONFIGDIR = 26
    GET_IS_IMAGE_LOADED = 27
    GET_IS_SEQUENCE_LOADED = 28
    GET_SELECTION = 29
    SET_SELECTION = 30
    GET_ACTIVE_VPORT = 31
    GET_STAR_IN_SELECTION = 32
    GET_STATS_FOR_SELECTION = 33
    PIX2WCS = 34
    WCS2PIX = 35
    UNDO_SAVE_STATE = 36
    GET_BUNDLE_PATH = 37
    ERROR_MESSAGEBOX = 38
    ERROR_MESSAGEBOX_MODAL = 39
    SIRIL_PLOT = 40
    CLAIM_THREAD = 41
    RELEASE_THREAD = 42
    SET_SEQ_FRAME_PIXELDATA = 43
    REQUEST_SHM = 44
    SET_SEQ_FRAME_INCL = 45
    GET_USERDATADIR = 46
    GET_SYSTEMDATADIR = 47
    GET_BGSAMPLES = 48
    SET_BGSAMPLES = 49
    GET_SEQ_FRAME_FILENAME = 50
    INFO_MESSAGEBOX = 51
    INFO_MESSAGEBOX_MODAL = 52
    WARNING_MESSAGEBOX = 53
    WARNING_MESSAGEBOX_MODAL = 54
    GET_SEQ_DISTODATA = 55
    SET_IMAGE_HEADER = 56
    ADD_USER_POLYGON = 57
    DELETE_USER_POLYGON = 58
    CLEAR_USER_POLYGONS = 59
    GET_USER_POLYGON = 60
    GET_USER_POLYGON_LIST = 61
    CONFIRM_MESSAGEBOX = 62
    GET_SEQ_FRAME_HEADER = 63
    CREATE_NEW_SEQ = 64
    CLEAR_BGSAMPLES = 65
    DRAW_POLYGON = 66
    GET_IMAGE_FILE = 67
    ANALYSE_IMAGE_FILE = 68
    UNDO = 69
    REDO = 70
    SET_IMAGE_ICCPROFILE = 71
    CLEAR_UNDO_HISTORY = 72
    GET_SLIDER_STATE = 73
    SET_SLIDER_MODE = 74
    SET_SLIDER_LOHI = 75
    GET_STFMODE = 76
    SET_STFMODE = 77
    GET_PANZOOM = 78
    SET_PAN = 79
    SET_ZOOM = 80
    GET_DISPLAY_ICC_PROFILE = 81
    GET_STF_LINKED = 82
    SET_STF_LINKED = 83
    SET_IMAGE_FILENAME = 84
    GET_SIRIL_LOG = 85
    SAVE_IMAGE_FILE = 86
    ERROR = 0xFF


@unique
class CommandStatus(IntEnum):
    """
    Contains Siril command status codes, matching the values
    returned internally within Siril. These can be used for
    error handling. CMD_OK and CMD_NO_WAIT are no-error codes;
    all the other codes represent command errors. These are
    available through the CommandError exception and may
    generally be handled without being regarded as fatal to
    the script.
    """

    CMD_NOT_FOUND = 1
    CMD_NO_WAIT = 1 << 1
    CMD_NO_CWD = 1 << 2
    CMD_NOT_SCRIPTABLE = 1 << 3
    CMD_WRONG_N_ARG = 1 << 4
    CMD_ARG_ERROR = 1 << 5
    CMD_SELECTION_ERROR = 1 << 6
    CMD_OK = 0
    CMD_GENERIC_ERROR = 1 << 7
    CMD_IMAGE_NOT_FOUND = 1 << 8
    CMD_SEQUENCE_NOT_FOUND = 1 << 9
    CMD_INVALID_IMAGE = 1 << 10
    CMD_LOAD_IMAGE_FIRST = 1 << 11
    CMD_ONLY_SINGLE_IMAGE = 1 << 12
    CMD_NOT_FOR_SINGLE = 1 << 13
    CMD_NOT_FOR_MONO = 1 << 14
    CMD_NOT_FOR_RGB = 1 << 15
    CMD_FOR_CFA_IMAGE = 1 << 16
    CMD_FILE_NOT_FOUND = 1 << 17
    CMD_FOR_PLATE_SOLVED = 1 << 18
    CMD_NEED_INIT_FIRST = 1 << 19
    CMD_ALLOC_ERROR = 1 << 20
    CMD_THREAD_RUNNING = 1 << 21
    CMD_DIR_NOT_FOUND = 1 << 22


class _Defaults:
    """
    Contains default values for different datatypes, matching Siril
    """

    DEFAULT_DOUBLE_VALUE = -999.0
    DEFAULT_FLOAT_VALUE = -999.0
    DEFAULT_INT_VALUE = -2147483647
    DEFAULT_UINT_VALUE = 2147483647
    VALUES = {DEFAULT_DOUBLE_VALUE, DEFAULT_FLOAT_VALUE, DEFAULT_INT_VALUE, DEFAULT_UINT_VALUE}


@unique
class _ConfigType(IntEnum):
    """
    Enumerates config variable types for use with the
    ``get_siril_config()`` method. Internal class: this is not intended
    for use in scripts.
    """

    BOOL = 0
    INT = 1
    DOUBLE = 2
    STR = 3
    STRDIR = 4
    STRLIST = 5


@unique
class BitpixType(IntEnum):
    """
    Mimics the Siril bitpix enum. Note that although Siril can
    handle opening FITS files of any data type, internally it processes
    images only as USHORT_IMG (uint16) or FLOAT_IMG (float32).
    """

    BYTE_IMG = 8
    SHORT_IMG = 16
    USHORT_IMG = 20
    LONG_IMG = 32
    FLOAT_IMG = -32
    DOUBLE_IMG = -64


@unique
class StarProfile(IntEnum):
    """
    Python equivalent of the Siril starprofile enum. Used to identify the type
    of fit used to model a star in the image. Note that MOFFAT_FIXED is currently
    not used in Siril, but is reserved for future use for Moffat stars modelled
    with a fixed beta parameter
    """

    GAUSSIAN = 0
    MOFFAT = 1
    MOFFAT_FIXED = 2


@unique
class SequenceType(IntEnum):
    """Python equivalent of the Siril sequence_type enum"""

    SEQ_REGULAR = 0
    SEQ_SER = 1
    SEQ_FITSEQ = 2
    SEQ_AVI = 3
    SEQ_INTERNAL = 4


@unique
class DistoType(IntEnum):
    """Python equivalent of the Siril disto_source enum"""

    DISTO_UNDEF = 0  #: No distortion
    DISTO_IMAGE = 1  #: Distortion from current image
    DISTO_FILE = 2  #: Distortion from given file
    DISTO_MASTER = 3  #: Distortion from master files
    DISTO_FILES = 4  #: Distortion stored in each file (true only from seq platesolve, even with no distortion, it will be checked upon reloading)
    DISTO_FILE_COMET = 5  #: special for cometary alignement, to be detected by apply reg


@unique
class PlotType(IntEnum):
    """Enumeration of available plot types for visualizing data series."""

    POINTS = 0
    MARKS = 1
    HYPHENS = 2
    LINES = 3
    LINESPOINTS = 4
    LINESMARKS = 5
    LINESHYPHENS = 6
