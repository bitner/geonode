import httplib2
import logging
from gsuploader.api import parse_response
from urlparse import urlparse
import os
import _util
import pprint
import json
import mimetypes
import codecs

_logger = logging.getLogger("gsuploader")

class Uploader(object):

    def __init__(self, url, username="admin", password="geoserver"):
        self.client = _Client(url,username,password)

    def _call(self,fun,*args):
        robj = fun(*args)
        if isinstance(robj, list):
            for i in robj:
                i._uploader = self
        else:
            robj._uploader = self
        return robj

    def get_sessions(self):
        return self._call(self.client.get_imports)
        
    def get_session(self,id):
        """Get an existing session by id.
        """
        return self._call(self.client.get_import,id)

    def start_import(self):
        """Create a new import session.
        returns a gsuploader.api.Session object
        """
        return self._call(self.client.start_import)
        
    def upload(self,fpath):
        """Try a complete import - create a session and upload the provided file.
        fpath can be a path to a zip file or the 'main' file if a shapefile or a tiff
        returns a gsuploader.api.Session object
        """
        files = [ fpath ]
        if fpath.endswith(".shp"):
            files = _util.shp_files(fpath)
            
        session = self.start_import()
        session.upload_task(files)

        return session
        
    # pickle protocol - client object cannot be serialized
    # this allows api objects to be seamlessly pickled and loaded without restarting
    # the connection more explicitly but this will have consequences if other state is stored
    # in the uploader or client objects
    def __getstate__(self):
        cl = self.client
        return {'url':cl.service_url,'username':cl.username,'password':cl.password}
    def __setstate__(self,state):
        self.client = _Client(state['url'],state['username'],state['password'])
            
        
                
        
class _Client(object):
    """Lower level http client"""

    # @todo some sanity on return values, either parsed object or resp,content tuple
    
    def __init__(self, url, username, password):
        self.service_url = url
        if self.service_url.endswith("/"):
            self.service_url = self.service_url.strip("/")
        self.http = httplib2.Http()
        self.username = username
        self.password = password
        self.http.add_credentials(self.username, self.password)
        netloc = urlparse(url).netloc
        self.http.authorizations.append(
            httplib2.BasicAuthentication(
                (username, password),
                netloc,
                url,
                {},
                None,
                None,
                self.http
            ))
            
    def url(self,path):
        return "%s/%s" % (self.service_url,path)

    def post(self, url):
        return self._request(url, "POST")
        
    def put_json(self, url, data):
        return self._request(url, "PUT", data, {
            "Content-type" : "application/json"
        })
    
    def _request(self, url, method="GET", data=None, headers={}):
        _logger.info("%s request to %s",method,url)
        resp, content = self.http.request(url,method,data,headers)
        _debug(resp, content)
        if resp.status < 200 or resp.status > 299:
            raise Exception('Server error',content)
        return resp, content
        
    def put_zip(self,url,payload):
        message = open(payload)
        with message:
            return self._request(url,"PUT",message,{
                "Content-type": "application/zip",
            })
            
    def get_import(self,i):
        return parse_response(self._request(self.url("imports/%s" % i)))

    def get_imports(self):
        return parse_response(self._request(self.url("imports")))
    
    def start_import(self):
        return parse_response(self._request(self.url("imports"),"POST"))
        
    def post_multipart(self,url,files,fields=[]):
        """
        fields is a sequence of (name, value) elements for regular form fields.
        files is a sequence of name or (name,filename) or (name, filename, value) 
        elements for data to be uploaded as files
        
        """
        BOUNDARY = '----------ThIs_Is_tHe_bouNdaRY_$'
        CRLF = '\r\n'
        L = []
        _logger.info("post_multipart %s %s %s",url,files,fields)
        for (key, value) in fields:
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"' % str(key))
            L.append('')
            L.append(str(value))
        for fpair in files:
            if isinstance(fpair,basestring):
                fpair = (fpair,fpair)
            key = fpair[0]
            if len(fpair) == 2:
                filename = os.path.basename(fpair[1])
                fp = open(fpair[1])
                value = fp.read()
                fp.close()
            else:
                filename, value = fpair[1:]
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (str(key), str(filename)))
            L.append('Content-Type: %s' % _get_content_type(filename))
            L.append('')
            L.append(value)
        L.append('--' + BOUNDARY + '--')
        L.append('')
        return self._request(
            url, 'POST', CRLF.join(L), {
                'Content-Type' : 'multipart/form-data; boundary=%s' % BOUNDARY
            }
        )
        
        
def _get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

def _debug(resp, content):
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("response : %s",pprint.pformat(resp))
        if "content-type" in resp and resp['content-type'] == 'application/json':
            content = json.loads(content) 
            content = json.dumps(content,indent=2)

        _logger.debug("content : %s",content)
