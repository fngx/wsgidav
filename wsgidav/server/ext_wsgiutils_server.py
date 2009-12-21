"""
Running WsgiDAV
===============

WsgiDAV comes bundled with a simple WSGI webserver.

Running as standalone server
----------------------------

To run as a standalone server using the bundled ext_wsgiutils_server.py:: 

        usage: python ext_wsgiutils_server.py [options] [config-file]
        
        config-file:
          The configuration file for WsgiDAV. if omitted, the application
          will look for a file named 'WsgiDAV.conf' in the current directory
        
        options:
          --port=PORT  Port to serve on (default: 8080)
          --host=HOST  Host to serve from (default: localhost, which is only
                            accessible from the local computer; use 0.0.0.0 to make your
                            application public)
          -h, --help   show this help message and exit
        
        
Running using other web servers
-------------------------------

To run it with other WSGI web servers, you can::
    
        from wsgidav.mainappwrapper import PyFileApp
        publish_app = PyFileApp('WsgiDAV.conf')   
        # construct the application with configuration file 
        # if configuration file is omitted, the application
        # will look for a file named 'WsgiDAV.conf'
        # in the current directory
 
where ``publish_app`` is the WSGI application to be run, it will be called with 
``publish_app(environ, start_response)`` for each incoming request, as described in 
WSGI <http://www.python.org/peps/pep-0333.html>

Note: if you are using the paster development server (from Paste <http://pythonpaste.org>), you can 
copy ``ext_wsgi_server.py`` to ``<Paste-installation>/paste/servers`` and use this server to run the 
application by specifying ``server='ext_wsgiutils'`` in the ``server.conf`` or appropriate paste 
configuration.


About ext_wsgiutils_server
--------------------------

ext_wsgiutils_server.py is an extension of the wsgiutils server in Paste. 
It supports passing all of the HTTP and WebDAV (rfc 2518) methods.

It includes code from the following sources:
``wsgiServer.py`` from wsgiKit <http://www.owlfish.com/software/wsgiutils/> under PSF license, 
``wsgiutils_server.py`` from Paste <http://pythonpaste.org> under PSF license, 
flexible handler method <http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/307618> under public domain. 

"""
from wsgidav.version import __version__
import socket


import SocketServer, BaseHTTPServer, urlparse
import sys, logging
import traceback
from wsgidav import util
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

_logger = util.getModuleLogger(__name__)

SERVER_ERROR = """\
<html>
  <head>
     <title>Server Error</title>
  </head>
  <body>
     <h1>Server Error</h1>
     A server error has occurred.  Please contact the system administrator for
     more information.
  </body>
</html>
"""

class ExtHandler (BaseHTTPServer.BaseHTTPRequestHandler):
    
    _SUPPORTED_METHODS = ["HEAD","GET","PUT","POST","OPTIONS","TRACE","DELETE","PROPFIND","PROPPATCH","MKCOL","COPY","MOVE","LOCK","UNLOCK"]
    
    def log_message (self, *args):
        pass
        
    def log_request (self, *args):
        pass
        
    def getApp (self):
        # We want fragments to be returned as part of <path> 
        _protocol, _host, path, _parameters, query, _fragment = urlparse.urlparse ("http://dummyhost%s" % self.path, 
                                                                                   allow_fragments=False)
        # Find any application we might have
        for appPath, app in self.server.wsgiApplications:
            if (path.startswith (appPath)):
                # We found the application to use - work out the scriptName and pathInfo
                pathInfo = path [len (appPath):]
                if (len (pathInfo) > 0):
                    if (not pathInfo.startswith ("/")):
                        pathInfo = "/" + pathInfo
                if (appPath.endswith ("/")):
                    scriptName = appPath[:-1]
                else:
                    scriptName = appPath
                # Return all this
                return app, scriptName, pathInfo, query
        return None, None, None, None

    def handlerFunctionClosure(self,name):
        def handlerFunction(*args,**kwargs):
            self.do_method()            
        return handlerFunction
                  
    def do_method(self):
        app, scriptName, pathInfo, query = self.getApp ()
        if (not app):
            self.send_error (404, "Application not found.")
            return
        self.runWSGIApp (app, scriptName, pathInfo, query)

    def __getattr__(self, name):
        if len(name)>3 and name[0:3] == "do_" and name[3:] in self._SUPPORTED_METHODS:
            return self.handlerFunctionClosure(name)
        else:
            self.send_error (501, "Method Not Implemented.")
            return

    def runWSGIApp (self, application, scriptName, pathInfo, query):
        logging.info ("Running application with SCRIPT_NAME %s PATH_INFO %s" % (scriptName, pathInfo))
        
        if self.command == "PUT":
            pass # breakpoint
        
        env = {"wsgi.version": (1, 0),
               "wsgi.url_scheme": "http",
               "wsgi.input": self.rfile,
               "wsgi.errors": sys.stderr,
               "wsgi.multithread": 1,
               "wsgi.multiprocess": 0,
               "wsgi.run_once": 0,
               "REQUEST_METHOD": self.command,
               "SCRIPT_NAME": scriptName,
               "PATH_INFO": pathInfo,
               "QUERY_STRING": query,
               "CONTENT_TYPE": self.headers.get("Content-Type", ""),
               "CONTENT_LENGTH": self.headers.get("Content-Length", ""),
               "REMOTE_ADDR": self.client_address[0],
               "SERVER_NAME": self.server.server_address[0],
               "SERVER_PORT": str(self.server.server_address[1]),
               "SERVER_PROTOCOL": self.request_version,
               }
        for httpHeader, httpValue in self.headers.items():
            if not httpHeader in ("Content-Type", "Content-Length"):
                env ["HTTP_%s" % httpHeader.replace ("-", "_").upper()] = httpValue
#        print env["REQUEST_METHOD"], env.get("HTTP_AUTHORIZATION")

        # Setup the state
        self.wsgiSentHeaders = 0
        self.wsgiHeaders = []

        try:
            # We have there environment, now invoke the application
            _logger.debug("runWSGIApp application()...")
            result = application (env, self.wsgiStartResponse)
            try:
                for data in result:
                    if data:
                        self.wsgiWriteData (data)
                    else:
                        _logger.debug("runWSGIApp empty data")
            finally:
                _logger.debug("runWSGIApp finally.")
                if hasattr(result, "close"):
                    result.close()
        except:
            _logger.debug("runWSGIApp caught exception...")
            errorMsg = StringIO()
            traceback.print_exc(file=errorMsg)
            logging.error (errorMsg.getvalue())
            if not self.wsgiSentHeaders:
                self.wsgiStartResponse("500 Server Error", [("Content-type", "text/html")])
            self.wsgiWriteData(SERVER_ERROR)
        
        if (not self.wsgiSentHeaders):
            # We must write out something!
            self.wsgiWriteData (" ")
        return

    def wsgiStartResponse (self, response_status, response_headers, exc_info=None):
        _logger.debug("wsgiStartResponse(%s, %s, %s)" % (response_status, response_headers, exc_info))
        if (self.wsgiSentHeaders):
            raise Exception ("Headers already sent and start_response called again!")
        # Should really take a copy to avoid changes in the application....
        self.wsgiHeaders = (response_status, response_headers)
        return self.wsgiWriteData

    def wsgiWriteData (self, data):
        if (not self.wsgiSentHeaders):
            status, headers = self.wsgiHeaders
            # Need to send header prior to data
            statusCode = status [:status.find (" ")]
            statusMsg = status [status.find (" ") + 1:]
            _logger.debug("wsgiWriteData: send headers '%s', %s" % (status, headers))
            self.send_response (int (statusCode), statusMsg)
            for header, value in headers:
                self.send_header (header, value)
            self.end_headers()
            self.wsgiSentHeaders = 1
        # Send the data
        try:
            self.wfile.write (data)
        except socket.error, e:
            # Suppress stack trace when client aborts connection disgracefully:
            # 10053: Software caused connection abort
            # 10054: Connection reset by peer
            if e[0] in (10053, 10054):
                print >>sys.stderr, "*** Caught socket.error: ", e
            else:  
                raise


class ExtServer (SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    def __init__ (self, serverAddress, wsgiApplications, serveFiles=1):
        BaseHTTPServer.HTTPServer.__init__ (self, serverAddress, ExtHandler)
        appList = []
        for urlPath, wsgiApp in wsgiApplications.items():
            appList.append ((urlPath, wsgiApp))
        self.wsgiApplications = appList
        self.serveFiles = serveFiles
        self.serverShuttingDown = 0


def serve(conf, app):
    host = conf.get("host", "localhost")
    port = int(conf.get("port", 8080)) 
    server = ExtServer((host, port), {"": app})
    if conf.get("verbose") >= 1:
        if host in ("", "0.0.0.0"):
            (hostname, _aliaslist, ipaddrlist) = socket.gethostbyname_ex(socket.gethostname())
            print "WsgiDAV %s serving at %s, port %s (host='%s' %s)..." % (__version__, host, port, hostname, ipaddrlist)
        else:
            print "WsgiDAV %s serving at %s, port %s..." % (__version__, host, port)
    server.serve_forever()


if __name__ == "__main__":
    raise RuntimeError("Use run_server.py")