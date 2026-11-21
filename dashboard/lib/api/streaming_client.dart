// The browser's default http client buffers the whole response, which would hide the live
// agent events until the end. On the web we use fetch(), which exposes the body as a stream.
export 'streaming_client_io.dart' if (dart.library.js_interop) 'streaming_client_web.dart';
