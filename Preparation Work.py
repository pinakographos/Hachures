#setup steps
import math
import time

start = time.time()
DEM = iface.activeLayer()
instance = QgsProject.instance()
crs = instance.crs()

#USER PARAMETERS
gridSpacing = 3
jumpDistance = 5
contourInterval = 5


#Step 1: Derive slope, aspect, and contours
params = {
    'INPUT': DEM,
    'OUTPUT': 'TEMPORARY_OUTPUT'
}

slopeLayer = QgsRasterLayer(processing.run('qgis:slope',params)['OUTPUT'],'Slope')
aspectLayer = QgsRasterLayer(processing.run('qgis:aspect',params)['OUTPUT'],'Aspect')

params['INTERVAL'] = contourInterval

contourPath = processing.run('gdal:contour_polygon',params)['OUTPUT']
contourLayer = QgsVectorLayer(contourPath, "Contour Layer", "ogr")

instance.addMapLayer(contourLayer, False)

#Step 2: Process the contours so that they are all in the needed format
#each contour is represented by a polygon showing all areas *higher* than that contour

contours = [(f.id(),f.attributeMap()['ELEV_MIN']) for f in contourLayer.getFeatures()]
contours.sort(key = lambda x: x[1])
#these were very likely already sorted, but let's not chance it

#make a simple rectangular layer covering the extent of our contours
extent = contourLayer.extent()
polygon = QgsGeometry.fromRect(extent)
feature = QgsFeature()
feature.setGeometry(polygon)

boundLayer = QgsVectorLayer("polygon", "temp", "memory")
boundLayer.setCrs(crs)


with edit(boundLayer):
    boundLayer.dataProvider().addFeature(feature)
    
# to prepare what we need, we need to iterate through each contour layer
# and subtract it from our simple rectangle — yielding rectangles with varying size holes
    
diffLayers = []

for i in range(0,len(contours)):
    selection = [x[0] for x in contours[0:i]]
    contourLayer.selectByIds(selection)
    
    params = {
        'INPUT': boundLayer,
        'OUTPUT': 'TEMPORARY_OUTPUT',
        'OVERLAY': QgsProcessingFeatureSourceDefinition(contourLayer.source(),selectedFeaturesOnly=True)
    }
    
    diff = processing.run("qgis:difference",params)['OUTPUT']
    diff.setName('{x}'.format(x = i))
    
    diffLayers.append(diff)
    
#merge all these layers together when done
    
params = {
        'LAYERS': diffLayers,
        'OUTPUT':'TEMPORARY_OUTPUT'
        }
            
merged = processing.run("qgis:mergevectorlayers",params)['OUTPUT']

#and rename the 'layer' field

field_idx = merged.fields().indexFromName('Layer')
with edit(merged):
    merged.renameAttribute(field_index, 'ELEV')
    
#finally, convert this to lines
params = {
        'INPUT': merged,
        'OUTPUT':'TEMPORARY_OUTPUT'
}

lines = processing.run("qgis:polygonstolines",params)['OUTPUT']

#Step 3: create downslope lines

#3.1 create grid of starting points for our lines
params = {
        'TYPE': 0, #this means a point grid, vs. hexagons &c.
        'HSPACING':gridSpacing,
        'VSPACING':gridSpacing,
        'OUTPUT':'TEMPORARY_OUTPUT',
        'CRS': crs,
        'EXTENT': extent
}

pointLayer = processing.run('qgis:creategrid',params)['OUTPUT']

#3.1 Set up the data so that we'll be able to pull info from the raster
provider = aspectLayer.dataProvider()
extent = provider.extent()
rows = aspectLayer.height()
cols = aspectLayer.width()
block = provider.block(1, extent, cols, rows)
#block.value(row,col) will now return pixel vals. It is indexed starting at 0 from the upper left.

#now grab data from the points layer
pointCoords = [(feat.geometry().asPoint().x(),feat.geometry().asPoint().y()) for feat in pointLayer.getFeatures()]

def getVal(location):

    row,col = location
    
    
    if row >= rows or col >= cols:
        return (-1,-1)
        
    if row < 0 or col < 0:
        return (-1,-1)
    
    return block.value(row,col)
    # this quick function just lets us specify a tuple of cell locations (row, column) & get the value


def xy2rc(location): #convert x/y coords to row/col
    x,y = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    col = round((x - extent.xMinimum()) / cellWidth - 0.5)
    row = round((extent.yMaximum() - y) / cellHeight - 0.5)
    
    return (row,col)
    

def rc2xy(location): #convert cell row/col to actual x/y coords
    row,col = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    x = cellWidth * (col + 0.5) + extent.xMinimum()
    y = extent.yMaximum() - cellHeight * (row + 0.5)    
    
    return(x,y)

def makeLines(coordList):
    #given a list of tuples with xy coords, this generates the line feature and adds it to the layer

    points = [QgsPointXY(x, y) for x, y in coordList]
    polyline = QgsGeometry.fromPolylineXY(points)
    feature = QgsFeature()
    feature.setGeometry(polyline)
    
    return feature

    
def dist(one,two):
    x1,y1 = one
    x2,y2 = two
    
    return math.sqrt((x1-x2)**2 + (y1-y2)**2)


flowLayer = QgsVectorLayer('LineString', 'Slopelines', 'memory')
flowLayer.setCrs(QgsProject.instance().crs())

lineProvider = flowLayer.dataProvider()

featureList = []

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
    
    
    for i in range (0,150): #this number ensures we don't bounce forever'
        
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
    
with edit(flowLayer):    
    lineProvider.addFeatures(featureList)

#add layers to ToC for user to review them prior to running next steps in process

lines.setName('Contour Lines')
instance.addMapLayer(slopeLayer)
instance.addMapLayer(lines)
instance.addMapLayer(flowLayer)
print(time.time() - start)
instance.removeMapLayer(contourLayer)