#ifdef USE_ARDUINO

#include "png_image.h"
#include "esphome/components/display/display_buffer.h"
#include "esphome/core/application.h"
#include "esphome/core/helpers.h"

#ifdef ONLINE_IMAGE_PNG_SUPPORT

static const char *const TAG = "online_image.png";

namespace esphome {
namespace online_image {

/**
 * @brief Callback method that will be called by the PNGLE engine when the basic
 * data of the image is received (i.e. width and height);
 *
 * @param pngle The PNGLE object, including the context data.
 * @param w The width of the image.
 * @param h The height of the image.
 */
static void initCallback(pngle_t *pngle, uint32_t w, uint32_t h) {
  PngDecoder *decoder = (PngDecoder *) pngle_get_user_data(pngle);
  decoder->set_size(w, h);
}

/**
 * @brief Callback method that will be called by the PNGLE engine when a chunk
 * of the image is decoded.
 *
 * @param pngle The PNGLE object, including the context data.
 * @param x The X coordinate to draw the rectangle on.
 * @param y The Y coordinate to draw the rectangle on.
 * @param w The width of the rectangle to draw.
 * @param h The height of the rectangle to draw.
 * @param rgba The color to paint the rectangle in.
 */
static void drawCallback(pngle_t *pngle, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint8_t rgba[4]) {
  PngDecoder *decoder = (PngDecoder *) pngle_get_user_data(pngle);
  Color color(rgba[0], rgba[1], rgba[2], rgba[3]);
  decoder->draw(x, y, w, h, color);
}

void PngDecoder::prepare(WiFiClient *stream, uint32_t download_size) {
  ImageDecoder::prepare(stream, download_size);
  pngle_set_user_data(pngle, this);
  pngle_set_init_callback(pngle, initCallback);
  pngle_set_draw_callback(pngle, drawCallback);
}

size_t HOT PngDecoder::decode(HTTPClient &http, WiFiClient *stream, std::vector<uint8_t> &buf) {
  int remain = 0;
  int downloaded = 0;
  uint8_t *buffer = buf.data();
  while (http.connected() && (downloaded < download_size_ || download_size_ == -1)) {
    App.feed_wdt();
    size_t size = stream->available();
    if (!size || size < buf.size() / 2 && download_size_ - downloaded > size) {
      delay(10);
      continue;
    }

    if (size > buf.size() - remain) {
      size = buf.size() - remain;
    }

    int len = stream->readBytes(buffer + remain, size);
    downloaded += len;
    if (len > 0) {
      int fed = pngle_feed(pngle, buffer, remain + len);
      if (fed < 0) {
        ESP_LOGE(TAG, "Error decoding image: %s", pngle_error(pngle));
        break;
      }

      remain = remain + len - fed;
      if (remain > 0) {
        memmove(buffer, buffer + fed, remain);
      }
    } else {
      delay(1);
    }
  }
  App.feed_wdt();
  return downloaded;
}

}  // namespace online_image
}  // namespace esphome

#endif  // ONLINE_IMAGE_PNG_SUPPORT

#endif  // USE_ARDUINO