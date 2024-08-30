from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

class OneRequestServer:
    def __init__(self, port=8080):
        self.server_address = ('', port)
        self.httpd = HTTPServer(self.server_address, self.RequestHandler)
        self.params = None

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Extract and store the query parameters in the parent server object
            query = urlparse(self.path).query
            self.server.params = parse_qs(query)

            # Respond to the client with a fancier HTML message
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            # Fancy HTML message
            html_response = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Authorization Complete</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        text-align: center;
                        padding: 50px;
                        background-color: #f4f4f4;
                    }
                    .container {
                        background-color: #fff;
                        padding: 20px;
                        border-radius: 10px;
                        box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);
                        display: inline-block;
                    }
                    h1 {
                        color: #4CAF50;
                    }
                    p {
                        font-size: 18px;
                        color: #555;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Authorization Complete</h1>
                    <p>You can now close this window and return to the application.</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html_response.encode('utf-8'))

        def log_message(self, format, *args):
            # Suppress default logging
            return

    def __enter__(self):
        # Return self to be used within the with block
        return self

    def wait_for_request(self):
        # Handle a single request and return the parameters
        self.httpd.handle_request()
        return self.httpd.params

    def __exit__(self, exc_type, exc_value, traceback):
        # Cleanup actions can be performed here if needed
        pass