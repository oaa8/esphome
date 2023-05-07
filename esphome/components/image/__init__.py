import logging

from pathlib import Path
import time
from reportlab.graphics import renderPM
import requests
from svglib.svglib import svg2rlg

from esphome import core
from esphome.components import display, font
import esphome.config_validation as cv
import esphome.codegen as cg
from esphome.const import (
    CONF_DITHER,
    CONF_FILE,
    CONF_ID,
    CONF_RAW_DATA_ID,
    CONF_RESIZE,
    CONF_TYPE,
)
from esphome.core import CORE, HexInt

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ["display"]
MULTI_CONF = True

ImageType = display.display_ns.enum("ImageType")
IMAGE_TYPE = {
    "BINARY": ImageType.IMAGE_TYPE_BINARY,
    "TRANSPARENT_BINARY": ImageType.IMAGE_TYPE_BINARY,
    "GRAYSCALE": ImageType.IMAGE_TYPE_GRAYSCALE,
    "RGB565": ImageType.IMAGE_TYPE_RGB565,
    "RGB24": ImageType.IMAGE_TYPE_RGB24,
    "RGBA": ImageType.IMAGE_TYPE_RGBA,
}

CONF_MDI = "mdi"
CONF_USE_TRANSPARENCY = "use_transparency"

# If a downloaded MDI image is older than this time, it will be redownloaded
MDI_CACHE_LIFETIME = 24 * 60 * 60  # seconds
# If the file cannot be downloaded within this time, abort.
MDI_DOIWNLOAD_TIMEOUT = 10  # seconds

Image_ = display.display_ns.class_("Image")


def validate_cross_dependencies(config):
    """
    Validate fields whose possible values depend on other fields.
    For example, validate that explicitly transparent image types
    have "use_transparency" set to True.
    Also set the default value for those kind of dependent fields.
    """
    if CONF_TYPE not in config:
        if CONF_MDI in config:
            config[CONF_TYPE] = "TRANSPARENT_BINARY"
        else:
            config[CONF_TYPE] = "BINARY"

    image_type = config[CONF_TYPE]
    is_transparent_type = image_type in ["TRANSPARENT_BINARY", "RGBA"]

    # If the use_transparency option was not specified, set the default depending on the image type
    if CONF_USE_TRANSPARENCY not in config:
        config[CONF_USE_TRANSPARENCY] = is_transparent_type

    if is_transparent_type and not config[CONF_USE_TRANSPARENCY]:
        raise cv.Invalid(f"Image type {image_type} must always be transparent.")

    if CONF_MDI in config and config[CONF_TYPE] not in ["BINARY", "TRANSPARENT_BINARY"]:
        raise cv.Invalid("MDI images must be binary images.")

    return config


IMAGE_SCHEMA = cv.Schema(
    cv.All(
        {
            cv.Required(CONF_ID): cv.declare_id(Image_),
            cv.Exclusive(CONF_FILE, "input"): cv.file_,
            cv.Exclusive(CONF_MDI, "input"): cv.string,
            cv.Optional(CONF_RESIZE): cv.dimensions,
            # Not setting default here on purpose; the default depends on the source type
            # (file or mdi), and will be set in the "validate_cross_dependencies" validator.
            cv.Optional(CONF_TYPE): cv.enum(IMAGE_TYPE, upper=True),
            # Not setting default here on purpose; the default depends on the image type,
            # and thus will be set in the "validate_cross_dependencies" validator.
            cv.Optional(CONF_USE_TRANSPARENCY): cv.boolean,
            cv.Optional(CONF_DITHER, default="NONE"): cv.one_of(
                "NONE", "FLOYDSTEINBERG", upper=True
            ),
            cv.GenerateID(CONF_RAW_DATA_ID): cv.declare_id(cg.uint8),
        },
        validate_cross_dependencies,
    )
)

CONFIG_SCHEMA = cv.All(font.validate_pillow_installed, IMAGE_SCHEMA)


async def to_code(config):
    from PIL import Image

    if CONF_FILE in config:
        path = CORE.relative_config_path(config[CONF_FILE])
        try:
            image = Image.open(path)
        except Exception as e:
            raise core.EsphomeError(f"Could not load image file {path}: {e}")
    elif CONF_MDI in config:
        # In case the prefix "mdi:" is present remove it.
        # This allows easily using the mdi intellisense VSCode extension
        mdi_id = config[CONF_MDI].removeprefix("mdi:")
        images_path = Path(CORE.build_path, "data", "images")
        svg_file = Path(images_path, f"{mdi_id}.svg")

        # If the image has not been downloaded yet, or is older than 24 hours, download it again.
        if (
            not svg_file.exists()
            or svg_file.stat().st_mtime + MDI_CACHE_LIFETIME < time.time()
        ):
            url = f"https://raw.githubusercontent.com/Templarian/MaterialDesign/master/svg/{mdi_id}.svg"
            _LOGGER.info("Downloading %s MDI image from %s", mdi_id, url)
            req = requests.get(url, timeout=MDI_DOIWNLOAD_TIMEOUT)
            if not req.ok:
                raise core.EsphomeError(
                    f"Could not download MDI image {mdi_id} from {url}: {req.status_code} - {req.reason}"
                )
            images_path.mkdir(parents=True, exist_ok=True)
            with svg_file.open(mode="w", encoding=req.encoding) as f:
                f.write(req.text)

        svg_image = svg2rlg(svg_file)
        if CONF_RESIZE in config:
            orig_width = svg_image.width
            orig_height = svg_image.height
            req_width, req_height = config[CONF_RESIZE]
            scale_x = req_width / orig_width
            scale_y = req_height / orig_height
            svg_image.width = req_width
            svg_image.height = req_height
            svg_image.scale(scale_x, scale_y)
        image = renderPM.drawToPILP(svg_image)

    width, height = image.size

    if CONF_RESIZE in config:
        if CONF_MDI not in config:
            image.thumbnail(config[CONF_RESIZE])
            width, height = image.size
    else:
        if width > 500 or height > 500:
            _LOGGER.warning(
                'The image "%s" you requested is very big. Please consider'
                " using the resize parameter.",
                path,
            )

    transparent = config[CONF_USE_TRANSPARENCY]

    dither = Image.NONE if config[CONF_DITHER] == "NONE" else Image.FLOYDSTEINBERG
    if config[CONF_TYPE] == "GRAYSCALE":
        image = image.convert("LA", dither=dither)
        pixels = list(image.getdata())
        data = [0 for _ in range(height * width)]
        pos = 0
        for g, a in pixels:
            if transparent:
                if g == 1:
                    g = 0
                if a < 127:
                    g = 1

            data[pos] = g
            pos += 1

    elif config[CONF_TYPE] == "RGBA":
        image = image.convert("RGBA")
        pixels = list(image.getdata())
        data = [0 for _ in range(height * width * 4)]
        pos = 0
        for r, g, b, a in pixels:
            data[pos] = r
            pos += 1
            data[pos] = g
            pos += 1
            data[pos] = b
            pos += 1
            data[pos] = a
            pos += 1

    elif config[CONF_TYPE] == "RGB24":
        image = image.convert("RGBA")
        pixels = list(image.getdata())
        data = [0 for _ in range(height * width * 3)]
        pos = 0
        for r, g, b, a in pixels:
            if transparent:
                if r == 0 and g == 0 and b == 1:
                    b = 0
                if a < 127:
                    r = 0
                    g = 0
                    b = 1

            data[pos] = r
            pos += 1
            data[pos] = g
            pos += 1
            data[pos] = b
            pos += 1

    elif config[CONF_TYPE] in ["RGB565"]:
        image = image.convert("RGBA")
        pixels = list(image.getdata())
        data = [0 for _ in range(height * width * 2)]
        pos = 0
        for r, g, b, a in pixels:
            R = r >> 3
            G = g >> 2
            B = b >> 3
            rgb = (R << 11) | (G << 5) | B

            if transparent:
                if rgb == 1:
                    rgb = 0
                if a < 127:
                    rgb = 1

            data[pos] = rgb >> 8
            pos += 1
            data[pos] = rgb & 255
            pos += 1

    elif config[CONF_TYPE] in ["BINARY", "TRANSPARENT_BINARY"]:
        if transparent:
            alpha = image.split()[-1]
            has_alpha = alpha.getextrema()[0] < 255
            _LOGGER.debug("%s Has alpha: %s", config[CONF_ID], has_alpha)
        image = image.convert("1", dither=dither)
        width8 = ((width + 7) // 8) * 8
        data = [0 for _ in range(height * width8 // 8)]
        for y in range(height):
            for x in range(width):
                if transparent and has_alpha:
                    a = alpha.getpixel((x, y))
                    if not a:
                        continue
                elif image.getpixel((x, y)):
                    continue
                pos = x + y * width8
                data[pos // 8] |= 0x80 >> (pos % 8)
    else:
        raise core.EsphomeError(
            f"Image f{config[CONF_ID]} has an unsupported type: {config[CONF_TYPE]}."
        )

    rhs = [HexInt(x) for x in data]
    prog_arr = cg.progmem_array(config[CONF_RAW_DATA_ID], rhs)
    var = cg.new_Pvariable(
        config[CONF_ID], prog_arr, width, height, IMAGE_TYPE[config[CONF_TYPE]]
    )
    cg.add(var.set_transparency(transparent))
