#setup steps
import math
import time

start = time.time()
DEM = iface.activeLayer() #the layer of interest must be selected
instance = QgsProject.instance()
crs = instance.crs()

#USER PARAMETERS
gridSpacing = 3
jumpDistance = 5
contourInterval = 3

#A few functions we'll need for later

#getVal accepts a row/column tuple and replies with the cell value at that location in the raster
def getVal(location):

    row,col = location
    
    
    if row >= rows or col >= cols:
        return (-1,-1)
        
    if row < 0 or col < 0:
        return (-1,-1)
    
    return block.value(row,col)


#xy2rc takes in a x/y coord tuple and finds the nearest matching row/column in our raster (so we can feed it into getVal)
def xy2rc(location): 
    x,y = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    col = round((x - extent.xMinimum()) / cellWidth - 0.5)
    row = round((extent.yMaximum() - y) / cellHeight - 0.5)
    
    return (row,col)
    
#rc2xy does the opposite of xy2rc
def rc2xy(location): 
    row,col = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    x = cellWidth * (col + 0.5) + extent.xMinimum()
    y = extent.yMaximum() - cellHeight * (row + 0.5)    
    
    return(x,y)

def makeLines(coordList):
    #given a list of tuples with xy coords, this generates a line feature connecting them

    points = [QgsPointXY(x, y) for x, y in coordList]
    polyline = QgsGeometry.fromPolylineXY(points)
    feature = QgsFeature()
    feature.setGeometry(polyline)
    
    return feature

#cartesian distance between two x/y pairs    
def dist(one,two):
    x1,y1 = one
    x2,y2 = two
    
    return math.sqrt((x1-x2)**2 + (y1-y2)**2)

#------------FUNCTION BLOCK DONE----------------

#------STEP 1: Derive slope, aspect, and contours using qgis/gdal built in tools--------
params = {
    'INPUT': DEM,
    'OUTPUT': 'TEMPORARY_OUTPUT'
}

slopeLayer = QgsRasterLayer(processing.run('qgis:slope',params)['OUTPUT'],'Slope')
aspectLayer = QgsRasterLayer(processing.run('qgis:aspect',params)['OUTPUT'],'Aspect')

params['INTERVAL'] = contourInterval

contourPath = processing.run('gdal:contour_polygon',params)['OUTPUT']
contourLayer = QgsVectorLayer(contourPath, "Contour Layer", "ogr")

instance.addMapLayer(contourLayer, False) #false means it doesn't show up in the table of contents
#(I didn't realize until far too late that you can't make selections on a layer unless it's added to the instance)

#-------STEP 2: Process the contours so that they are all in the needed format------
#Each contour will be represented by a polygon showing all areas *higher* than that contour

#First we ned to sort these to ensure we take them in the right order. They probably were already sorted in this order when made
#but let's not chance it.

contours = [(f.id(),f.attributeMap()['ELEV_MIN']) for f in contourLayer.getFeatures()]
contours.sort(key = lambda x: x[1])
#this list now holds tuples for each contour of the format (id, elevation)

#---STEP 2A: Let's now make a simple rectangular layer covering the extent of our contours
extent = contourLayer.extent()
polygon = QgsGeometry.fromRect(extent)
feature = QgsFeature()
feature.setGeometry(polygon)

boundLayer = QgsVectorLayer("polygon", "temp", "memory")
boundLayer.setCrs(crs)

with edit(boundLayer):
    boundLayer.dataProvider().addFeature(feature)

#---STEP 2B: We need to iterate through each contour layer and subtract it from our simple rectangle
# Thus yielding rectangles with varying size holes
    
diffLayers = []

for i in range(0,len(contours)):
    selection = [x[0] for x in contours[0:i]] #grab the contour IDs for contour i and all which are at a lower elevation than it
    contourLayer.selectByIds(selection)
    
    params = {
        'INPUT': boundLayer,
        'OUTPUT': 'TEMPORARY_OUTPUT',
        'OVERLAY': QgsProcessingFeatureSourceDefinition(contourLayer.source(),selectedFeaturesOnly=True)
    }
    
    diff = processing.run("qgis:difference",params)['OUTPUT']
    diff.setName('{x}'.format(x = i))
    
    diffLayers.append(diff)

#merge all these layers together when done, so we have all the different hole polygons
    
params = {
        'LAYERS': diffLayers,
        'OUTPUT':'TEMPORARY_OUTPUT'
        }
            
merged = processing.run("qgis:mergevectorlayers",params)['OUTPUT']

    
#finally, convert this to lines
params = {
        'INPUT': merged,
        'OUTPUT':'TEMPORARY_OUTPUT'
}

lines = processing.run("qgis:polygonstolines",params)['OUTPUT']

#------STEP 3: Create slopelines

#--STEP 3A: create grid of starting points for our lines
params = {
        'TYPE': 0, #0 means a point grid, vs. hexagons &c.
        'HSPACING':gridSpacing,
        'VSPACING':gridSpacing,
        'OUTPUT':'TEMPORARY_OUTPUT',
        'CRS': crs,
        'EXTENT': extent
}

pointLayer = processing.run('qgis:creategrid',params)['OUTPUT']

#--STEP 3B: Set up so we can easily pull from the aspect raster

provider = aspectLayer.dataProvider()
extent = provider.extent()
rows = aspectLayer.height()
cols = aspectLayer.width()
block = provider.block(1, extent, cols, rows)
#block.value(row,col) will now return pixel vals. It is indexed starting at 0 from the upper left.

#--STEP 3C: Now grab data from the points layer

#first we grab all grid point locations into a list of x,y tuples
pointCoords = [(feat.geometry().asPoint().x(),feat.geometry().asPoint().y()) for feat in pointLayer.getFeatures()]


featureList = [] #we'll assemble our line features here

#--STEP 3D: Below, we loop through every point. We take that point and use the underlying aspect to
#find the next point, then continue until we've built a line going downslope.

for c in pointCoords:
    lineCoords = [c]
    
    x,y = c
    rc = xy2rc(c)
    value = getVal(rc)
    
    if value == (-1,-1):

        continue
    
    #gotta try to remember trig from 11th grade
    #aspect raster is clockwise from north
    
    newx = x + math.sin(math.radians(value)) * jumpDistance
    newy = y + math.cos(math.radians(value)) * jumpDistance
    
    lineCoords += [(newx,newy)]
    
    #print(lineCoords)
    
    
    for i in range (0,150): #this number ensures we don't bounce forever, until I have a better solution
        
        x,y = lineCoords[-1]
        rc = xy2rc(lineCoords[-1])
        value = getVal(rc)
        if value == (-1,-1):

            break
        
        newx = x + math.sin(math.radians(value)) * jumpDistance
        newy = y + math.cos(math.radians(value)) * jumpDistance
        
        if (newx,newy) in lineCoords:

            break
            
        #lines tend to bounce back and forth as they near a sink. Need to check somehow for that.

        if len(lineCoords) > 3 and dist(lineCoords[-1],lineCoords[-3]) < (jumpDistance / 2):
            break

        lineCoords += [(newx,newy)]
        
    featureList.append(makeLines(lineCoords))
    
slopeLineLayer = QgsVectorLayer('LineString', 'Slopelines', 'memory')
slopeLineLayer.setCrs(QgsProject.instance().crs())
  
with edit(slopeLineLayer):    
    slopeLineLayer.dataProvider().addFeatures(featureList)

#----STEP 4: add layers to ToC for user to review them prior to running next steps in process

lines.setName('Contour Lines')
instance.addMapLayer(slopeLayer)
instance.addMapLayer(lines)
instance.addMapLayer(slopeLineLayer)
print(time.time() - start)
instance.removeMapLayer(contourLayer)
