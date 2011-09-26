#!/usr/bin/python

#downloaded from https://github.com/newsapps/making-maps-demo/blob/master/render_tiles.py

from math import pi,cos,sin,log,exp,atan
from subprocess import call
import sys, os
from Queue import Queue
import mapnik2
import threading
import argparse

custom_fonts_dir = '/Library/Fonts/'
mapnik2.register_fonts(custom_fonts_dir)

aggregate=16

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi

# Default number of rendering threads to spawn, should be roughly equal to number of CPU cores available
NUM_THREADS = 4

def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a

class GoogleProjection:
    def __init__(self,levels=18):
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        c = 256
        for d in range(0,levels):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
                
    def fromLLtoPixel(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def fromPixelToLL(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)



class RenderThread:
    def __init__(self, tile_dir, mapfile, q, printLock, maxZoom):
        self.tile_dir = tile_dir
        self.q = q
        self.m = mapnik2.Map(256, 256)
        self.printLock = printLock
        # Load style XML
        mapnik2.load_map(self.m, mapfile, True)
        # Obtain <Map> projection
        self.prj = mapnik2.Projection(self.m.srs)
        # Projects between tile pixel co-ordinates and LatLong (EPSG:4326)
        self.tileproj = GoogleProjection(maxZoom+1)


    def render_tile(self, tile_dir, x, y, z):
        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * 256 * aggregate, (y + 1) * 256 * aggregate)
        p1 = ((x + 1) * 256 * aggregate, y * 256 * aggregate)

        # Convert to LatLong (EPSG:4326)
        l0 = self.tileproj.fromPixelToLL(p0, z);
        l1 = self.tileproj.fromPixelToLL(p1, z);

        # Convert to map projection (e.g. mercator co-ords EPSG:900913)
        c0 = self.prj.forward(mapnik2.Coord(l0[0],l0[1]))
        c1 = self.prj.forward(mapnik2.Coord(l1[0],l1[1]))

        # Bounding box for the tile
        if hasattr(mapnik2,'mapnik_version') and mapnik2.mapnik_version() >= 800:
            bbox = mapnik2.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik2.Envelope(c0.x,c0.y, c1.x,c1.y)
        render_size = 256 * aggregate
        self.m.resize(render_size, render_size)
        self.m.zoom_to_box(bbox)
        self.m.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik2.Image(render_size, render_size)
        mapnik2.render(self.m, im)

        for i in range(0,aggregate):
           # check if we have directories in place
           str_x = "%s" % (x * aggregate + i)
           zoom = "%s" % z
           if not os.path.isdir(tile_dir + zoom + '/' + str_x):
               os.mkdir(tile_dir + zoom + '/' + str_x)
           for j in range(0,aggregate):
              view = im.view(i*256,j*256,256,256)
              #print(i*256,j*256,(i+1)*256,(j+1)*256)
              str_y = "%s" % (y * aggregate + j)
              tile_uri = tile_dir + zoom + '/' + str_x + '/' + str_y + '.png'
              view.save(tile_uri, 'png256')


    def loop(self):
        while True:
            #Fetch a tile from the queue and render it
            r = self.q.get()
            if (r == None):
                self.q.task_done()
                break
            else:
                (name, tile_dir, x, y, z) = r
            tile_uri = "%s%s/%s/%s.png" % (tile_dir, z, x*aggregate, y*aggregate)

            exists= ""
            if os.path.isfile(tile_uri):
                exists= "exists"
            else:
                self.render_tile(tile_uri, x, y, z)
            bytes=os.stat(tile_uri)[6]
            empty= ''
            if bytes == 103:
                empty = " Empty Tile "
            self.printLock.acquire()
            print name, ":", z, x*aggregate, y*aggregate, exists, empty
            self.printLock.release()
            self.q.task_done()



def render_tiles(bbox, mapfile, tile_dir, minZoom=1,maxZoom=18, name="unknown", num_threads=NUM_THREADS):
    print "render_tiles(",bbox, mapfile, tile_dir, minZoom, maxZoom, name,")"

    # Launch rendering threads
    queue = Queue(32)
    printLock = threading.Lock()
    renderers = {}
    for i in range(num_threads):
        renderer = RenderThread(tile_dir, mapfile, queue, printLock, maxZoom)
        render_thread = threading.Thread(target=renderer.loop)
        render_thread.start()
        #print "Started render thread %s" % render_thread.getName()
        renderers[i] = render_thread

    if not os.path.isdir(tile_dir):
         os.mkdir(tile_dir)

    gprj = GoogleProjection(maxZoom+1) 

    ll0 = (bbox[0],bbox[3])
    ll1 = (bbox[2],bbox[1])

    for z in range(minZoom,maxZoom + 1):
        px0 = gprj.fromLLtoPixel(ll0,z)
        px1 = gprj.fromLLtoPixel(ll1,z)
        
        # check if we have directories in place
        zoom = "%s" % z
        if not os.path.isdir(tile_dir + zoom):
            os.mkdir(tile_dir + zoom)
        for x in range(int(px0[0]/(256.0*aggregate)),int(px1[0]/(256.0*aggregate))+1):
            # Validate x co-ordinate
            if (x < 0) or (x >= 2**z):
                continue
            # check if we have directories in place
            str_x = "%s" % x
            for y in range(int(px0[1]/(256.0*aggregate)),int(px1[1]/(256.0*aggregate))+1):
                # Validate x co-ordinate
                if (y < 0) or (y >= 2**z):
                    continue
                str_y = "%s" % y
                # Submit tile to be rendered into the queue
                t = (name, tile_dir, x, y, z)
                queue.put(t)

    # Signal render threads to exit by sending empty request to queue
    for i in range(num_threads):
        queue.put(None)
    # wait for pending rendering jobs to complete
    queue.join()
    for i in range(num_threads):
        renderers[i].join()


if __name__ == "__main__":
    
    #python render_tiles.py tilemill/wards.xml mayor-2011/.tiles/wards/ -89.03 41.07 -87.51 42.50 9 16 2
    parser = argparse.ArgumentParser(description='Render your tiles.')
    parser.add_argument('style_file', help="File containing Mapnik styles")
    parser.add_argument('tile_dir', help="Destination directory for rendered tiles")
    parser.add_argument('lat_1', type=float, help="Top-left corner latitude")
    parser.add_argument('lon_1', type=float, help="Top-left corner longitude")
    parser.add_argument('lat_2', type=float, help="Bottom-right corner latitude")
    parser.add_argument('lon_2', type=float, help="Bottom-right corner longitude")
    parser.add_argument('min_zoom', help="Minimum zoom level to render", type=int, default="9")
    parser.add_argument('max_zoom', help="Maximum zoom level to render", type=int, default="12")
    parser.add_argument('cores', help="Number of rendering threads to spawn, should be roughly equal to number of CPU cores available", type=int, default="2")
    args = parser.parse_args()
    
    bbox = (args.lon_1, args.lat_2, args.lon_2, args.lat_1)
    
    render_tiles(bbox, args.style_file, args.tile_dir, args.min_zoom, args.max_zoom)
