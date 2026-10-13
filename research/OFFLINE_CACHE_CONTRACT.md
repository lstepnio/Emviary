# Offline cache response contract v1

Clients opt in on the existing authenticated image request with
`X-Emviary-Offline-Version: 1`. Successful 200 image responses may carry
`X-Emviary-Offline`. EPDGZ body bytes, ETag, configuration and recovery digests
are unchanged. No second download is required. A 304 has no admission metadata.

The response header is ASCII base64 of compact JSON, at most 4096 bytes:

```json
{"v":1,"id":"123","sha":"<64 lowercase hexadecimal body SHA256>","eligible":true,"season":"autumn","patch":{"x":200,"y":10,"w":580,"h":36,"z":"<base64 zlib bytes>"}}
```

`id` is a numeric image ID represented as a string. `season` is spring, summer,
autumn, winter or evergreen. Seasonal decoration enabled yields the rendered
season; decoration disabled yields evergreen. Special days, previews of special
days and event-only art instead receive `{"v":1,"eligible":false}`. Legacy
compositions, missing or invalid patches and unsupported geometry have no header
and must not be admitted. The implementation currently admits landscape 800x480
only; it does not invent a portrait patch.

The tile contains high-nibble-first packed 4bpp panel indices, even width, each
row packed independently. The firmware contract permits up to 64KiB inflated and
2048 compressed bytes. Backend validation rejects wrong dimensions, unsupported
inks, oversized data, malformed zlib, trailing data and decompression bombs.

Renderer v20 captures the actual header background, including any location text,
before drawing weather. Weather text, temperatures and icon are drawn onto a
separate transparent layer and clipped to exactly the tile rectangle. No bird,
seasonal motif or border is erased. The full weather-free canvas is converted with the exact same production
converter and settings, then the tile is extracted from its packed EPDGZ bytes.
There is no grayscale approximation: all six palette indices are retained,
including future colored header decoration or overlapping artwork. Source tests
compare weather and weather-free compositions and prove all weather-induced
source differences are inside the tile; a colored palette fixture proves exact
packed extraction. This costs one additional converter execution per newly
prepared ordinary image. Extra full-size files exist only inside the worker's
existing temporary directory and are deleted afterward. No second frame request,
full image transfer or persistent alternate image is needed.

The patch is stored in both the immutable image manifest and the retry job plan.
Rendering failure cannot publish an image, and retries preserve the chosen plan.
Admission binds metadata to the complete compressed EPDGZ SHA256 and requires a
complete verified body plus successful display. The original body remains intact.

Normal device metrics may report `offline_mode` (boolean), `offline_image_id`
(integer), `offline_cache_count` (0..256), `offline_cache_bytes` (0..16MiB), and
`offline_rotations` (0..2^32-1). These piggyback on existing check-ins. Public and
management previews explicitly identify the last cloud-confirmed picture and
explain that offline local rotation cannot be mirrored in real time. Cloud
confirmation is delivery evidence, not physical panel confirmation.
