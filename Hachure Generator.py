# before 88
import math
import time
import statistics

from qgis.PyQt.QtCore import (
    QVariant
)
from qgis.utils import iface
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsField,
    QgsProcessingFeatureSourceDefinition,
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    edit
)
from qgis import processing

#USER PARAMETERS
#mind your units. 
#A good starting min/max spacing is around a few times the pixel size of your DEM
minSpacing = 2   #(in Map Units)
maxSpacing = 4

contourInterval = 1 #in DEM z units

slopeMin = 15 #degrees
slopeMax = 45

#Preparatory work
DEM = iface.activeLayer() #For now, the layer of interest must be selected
instance = QgsProject.instance()
crs = instance.crs()
start = time.time()
spacingRange = maxSpacing - minSpacing
slopeRange = slopeMax - slopeMin

#----STEP 0: Derive slope, aspect, and contours using qgis/gdal built in tools------
params = {
    'INPUT': DEM,
    'OUTPUT': 'TEMPORARY_OUTPUT'
}

slopeLayer = QgsRasterLayer(processing.run('qgis:slope',params)['OUTPUT'],'Slope')
aspectLayer = QgsRasterLayer(processing.run('qgis:aspect',params)['OUTPUT'],'Aspect')

params['INTERVAL'] = contourInterval

contourPath = processing.run('gdal:contour_polygon',params)['OUTPUT']
filledContours = QgsVectorLayer(contourPath, "Contour Layer", "ogr")
instance.addMapLayer(filledContours,False)

#---STEP 0.5: Prepare the rasters for reading; assumption is that both are identical in extent & resolution
provider = slopeLayer.dataProvider()
extent = provider.extent()
rows = slopeLayer.height()
cols = slopeLayer.width()
slopeBlock = provider.block(1, extent, cols, rows)

aspectBlock = aspectLayer.dataProvider().block(1, extent, cols, rows)

avgPixel = 0.5 * (slopeLayer.rasterUnitsPerPixelX() + slopeLayer.rasterUnitsPerPixelY())
jumpDistance = avgPixel * 3



#------FUNCTION DEFINITIONS--------

#Converts x/y coords to row/col for sampling the slope or aspect raster
def xy2rc(location):
    x,y = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    col = round((x - extent.xMinimum()) / cellWidth - 0.5)
    row = round((extent.yMaximum() - y) / cellHeight - 0.5)
    
    return (row,col)

#samples the slope or aspect raster
def getVal(location,type = 0):
 
    row,col = location
    
    if row >= rows or col >= cols:
        return 0
        
    if row < 0 or col < 0:
        return 0
    
    if type == 0:
        return slopeBlock.value(row,col)
    else:
        return aspectBlock.value(row,col)
    
#Adds some attributes to a layer: ID, length, and optionally also gets the average slope covered by each feature in the layer
def attribution(layer,prefix,getSlope = False):

    pv = layer.dataProvider()

    fields = [QgsField(prefix + 'ID', QVariant.Int), QgsField(prefix + 'Length', QVariant.Double)]
    
    if getSlope:
        fields += [QgsField('Slope', QVariant.Double)]
    
    with edit(layer):
        pv.addAttributes(fields)
        layer.updateFields()  # Update the fields in the layer
        
    attributeMap = {}
    
    fields = layer.fields()

    fieldDict = dict(zip(fields.names(),fields.allAttributesList()))
    
    ID_idx = fieldDict[prefix + 'ID']
    len_idx = fieldDict[prefix +  'Length']
    if getSlope:
        slope_idx = fieldDict['Slope']

    for feature in layer.getFeatures():
    
        attributeMap[feature.id()] = {ID_idx: feature.id(), len_idx: feature.geometry().length()}
        if getSlope:
            attributeMap[feature.id()][slope_idx] = getAverageSlope(feature)
     
    pv.changeAttributeValues(attributeMap)
    
    
#when given a slope, this determines the ideal spacing of slopelines based on the parameters entered by the user
def splitSpacing(slope):
    if slope > slopeMax:
        slope = slopeMax
    elif slope < slopeMin:
        return None
        
    slopePct = (slope - slopeMin) / slopeRange
    spacingQty = slopePct * spacingRange
    
    spacing = maxSpacing - spacingQty
    
    return spacing
    
def getAverageSlope(contourSnippet):

    #this function gets a line feature passed to it, and returns the avg slope that that feature covers
    
    #first we need to shove this feature into a layer so we can easily densify it.
    #instead of using QGIS processing, I could potentially later on speed this up by sampling the feature's vertices and densifying it within the script
    
    
    tempLayer = QgsVectorLayer("LineString", "temp", "memory")
    tempLayer.setCrs(crs)
    with edit(tempLayer):
            tempLayer.dataProvider().addFeatures([contourSnippet])

  
    #ok, add points approximatly every pixel width along the line
    
    params = {
        'INPUT': tempLayer,
        'OUTPUT': 'TEMPORARY_OUTPUT',
        'INTERVAL': avgPixel
    }
    
    densified = processing.run('qgis:densifygeometriesgivenaninterval',params)['OUTPUT']
    line = next(densified.getFeatures())
    lineGeo = line.geometry().asPolyline()
    vertices = [(vertex.x(), vertex.y()) for vertex in lineGeo]
    
    
    rcTuples = [xy2rc(c) for c in vertices]
    
    values = [getVal(c,0) for c in rcTuples]
        
    #this is all the values sampled from the raster. Average it.
    
    try:
        stats = statistics.fmean(values)
    except:
        return 0
    return stats
    

def contourSubstrings(tooLongLayer):
    #this func receives a layer of contour splits that were "too long" and may need 1 or more new slopelines to start among them
    instance.addMapLayer(tooLongLayer,False)
    outputLines = []
    
    for feature in tooLongLayer.getFeatures():
        slope = feature.attributeMap()['Slope']
        if slope < slopeMin:
            continue
                
        spacing = splitSpacing(slope)
        
        #ok, let's align the dash/gap to the feature length so we get an even split
        #this is much like Illustrator's function to align dashes
        
        totalLength = spacing * 2 #the length of a gap + dash + gap
        segmentLength = feature.attributeMap()['SplitLength']
        totalSplits = round(segmentLength / totalLength)
        
        if totalSplits == 0:
            #This value was possible in older versions. Maybe not now; but let's catch it anyway.
            continue
        
        dashGapLength = segmentLength / totalSplits

        dashWidth = dashGapLength / 2 # half of our gap-dash-gap is the dash
        gapWidth = dashWidth / 2

        startPoint = gapWidth
    
        endPoint = dashWidth + gapWidth
            
        tooLongLayer.selectByIds([feature.id()])

        while True:

            #create the splits
            params = {
                'INPUT': QgsProcessingFeatureSourceDefinition(tooLongLayer.source(),selectedFeaturesOnly=True),
                'START_DISTANCE': startPoint,
                'END_DISTANCE': endPoint,
                'OUTPUT':'TEMPORARY_OUTPUT'
                }
            output = processing.run("qgis:linesubstring",params)['OUTPUT']
            outputLines.append(output)

            startPoint += dashGapLength
            endPoint += dashGapLength

            if endPoint > segmentLength:

               break

    instance.removeMapLayer(tooLongLayer)
    
    #now let's join together all the output lines

    if len(outputLines) > 0: #once again, in case our splits all ended up being too short
        params = {
        'LAYERS': outputLines,
        'OUTPUT':'TEMPORARY_OUTPUT'
        }
            
        merged = processing.run("qgis:mergevectorlayers",params)['OUTPUT']
      

        #once it comes back to us, we'll add an ID field
        attributeMap = {}
        field = QgsField('SplitID', QVariant.Int)
        
        with edit(merged):
            merged.addAttribute(field)
            merged.updateFields()
            
        ID_idx = merged.fields().indexFromName('SplitID')
        for feature in merged.getFeatures():
            attributeMap[feature.id()] = {ID_idx: feature.id()}
            

        merged.dataProvider().changeAttributeValues(attributeMap)
      
        return merged
    
    else:
        return None 


#this next function clips all our slopelines by the contour
#it keeps the part of the slopeline at a higher elevation than the contour

def clipToContour(contourPoly,linesToClip):
     
    #we want to find all slopelines that intersect the poly, so that we only consider slopelines from the contour on up the slope.

    params = {
            'INPUT': linesToClip,
            'OVERLAY': contourPoly,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    candidateLines = processing.run("qgis:intersection", params)['OUTPUT']
    

    #let's add ID values and lengths after clipping the slopelines to the poly. We'll need these later
    
    attribution(candidateLines,'Line')
   
  
    candidateLines.dataProvider().createSpatialIndex() #this will help future processes go faster

    #these are all the lines that we want to check

    return candidateLines




            
#This is run on the first contour line to check which slopelines intersect it. It's a simplified version of the main loop function, spacingCheck, below.

def firstLine(contour):
    global currentSlopeLines
    #1st we divide initial contour into chunks
   
    params = {
            'INPUT': contour,
            'LENGTH': maxSpacing * 3,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    splitLines = processing.run("qgis:splitlinesbylength",params)['OUTPUT']
    
    #next let's give the splits a needed attribute or two
    
    pv = splitLines.dataProvider()

    attribution(splitLines,'Split',True)
   
    pv.createSpatialIndex() #this will help future processes go faster

    #we split it into dashes according to its slope
    newOnes = contourSubstrings(splitLines)
    
    if newOnes:
        additions = newLines(newOnes)
        return additions
    else:
        return None
    
#All subsequent contours past the first one are run through here.
def spacingCheck(contour):
    global currentHachures
    #1st we run split w/ lines to split the contour according to the existing slopelines
    
    params = {
            'INPUT': contour,
            'LINES': currentHachures,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    preSplitLines = processing.run("qgis:splitwithlines",params)['OUTPUT']
    
    #we need to then further subdivide this. It's possible that some of the splits
    #are so big that their slope calculations are no longer local

    params = {
            'INPUT': preSplitLines,
            'LENGTH': maxSpacing * 3,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
    splitLines = processing.run("qgis:splitlinesbylength",params)['OUTPUT']
    
    #next let's give the splits a needed attribute or two.
    
    attribution(splitLines,'Split',True)
    
    tooShort = []
    tooLong = []

    for feat in splitLines.getFeatures():
        idealSpacing = splitSpacing(feat.attributeMap()['Slope'])
        leng = feat.attributeMap()['SplitLength']
        if idealSpacing == None or leng < idealSpacing:
            tooShort.append(feat)
        elif leng >= idealSpacing * 2:
            tooLong.append(feat)
            
    #now we know which splits are (probably) too short and which are (probably) too long
    #and they exist in their own layers
    
    #a "too short" split means that it spans two slopelines that are too close: we need to cut one off
    #"too long" means that we should maybe start a new slope line
    
    #first, if a split is "too short," we need to confirm it touches exactly two slopelines
    #and then figure out what their identity is, because we need to clip one or both later
    
    #spatial joins in QGIS are very unreliable when features share exactly one point.
    #so this is my workaround:
        
        
    tooShortLayer = QgsVectorLayer("LineString", "temp", "memory")
    tooShortLayer.setCrs(crs)
    with edit(tooShortLayer):
        tooShortLayer.dataProvider().addFeatures(tooShort)
        
    attribution(tooShortLayer,'Split',True)
        
    params = {
        'INPUT': tooShortLayer,
        'VERTICES': '0,-1',
        'OUTPUT':'TEMPORARY_OUTPUT'
        }

            
    interPoints = processing.run("qgis:extractspecificvertices",params)['OUTPUT']
    
    #now we buffer the intersection points a tiny bit — again because QGIS is bad at spatial joins
    
    params = {
            'INPUT': interPoints,
            'DISTANCE': 0.01,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
    buffers = processing.run("qgis:buffer", params)['OUTPUT']
    buffers.dataProvider().createSpatialIndex()
    
    
    params = {
        'INPUT' : buffers,
        'PREDICATE': [0],
        'JOIN': currentHachures,
        'METHOD': 0, # = intersect
        'DISCARD_NONMATCHING':True,
        'OUTPUT':'TEMPORARY_OUTPUT',
        'JOIN_FIELDS': ['LineID','LineLength']
    }

    joinLayer = processing.run('qgis:joinattributesbylocation',params)['OUTPUT']
    
    
    #now we can construct a dataset that tells us, for each split, which lines it touches
    #we only care about the splits that touch two lines
    #the rest are danglers of some sort
    
    neighbors = {}
    toClipBoth = []
    for feat in joinLayer.getFeatures():
        
        id = feat.attributeMap()['SplitID']
        
        if id not in neighbors:
            neighbors[id] = [feat.attributeMap()]
        else:
            neighbors[id] += [feat.attributeMap()]
            
        if feat.attributeMap()['Slope'] < slopeMin:
            toClipBoth.append(id)
        

    #the neighbors dict now is of the form {SplitID: [lines it touches]}
    #need to clean it, as some lines only will touch one point due to ring closure issues    

    splitsToKeep = [key for key in neighbors if len(neighbors[key]) == 2] #this is a series of IDs of splits to delete
    
    #we now know which splits are between slopelines that are too close
    #for these shorter ones, we need to keep the longest and clip the other.
    #or sometimes we should clip off both if the slope is too shallow and the line made it into the toClipBoth list
    
    toClip = []
    
    for split in splitsToKeep:
        slopeLinesData = neighbors[split]

        lineOne =slopeLinesData[0]
        lineTwo =slopeLinesData[1]
        
        if split in toClipBoth:
            toClip += [lineTwo['LineID'], lineOne['LineID']]
        else:
            #there are only two lines touching this split, so let's just compare each directly
            if lineOne['LineLength'] > lineTwo['LineLength']:
                toClip.append(lineTwo['LineID'])
            else:
                toClip.append(lineOne['LineID'])
    
    
    #we know which slopelines from this set need clipping. Put them in a layer.
    
    targets = [feat for feat in currentHachures.getFeatures() if feat.attributeMap()['LineID'] in toClip]
    
    
    toClipLayer = QgsVectorLayer("LineString", "temp", "memory")
    toClipLayer.setCrs(crs)
    with edit(toClipLayer):
        toClipLayer.dataProvider().addFeatures(targets) 
                    
    #and remove them from the existng layer

    with edit(currentHachures):
        toDelete = [f.id() for f in targets]
        currentHachures.deleteFeatures(toDelete) 
        
    clippedLines = haircut(contour,toClipLayer)
    
    #now we've clipped off some of the lines
    #Let's next deal with adding more in the "too long" splits
    
    #shove all longs into a single layer and pass it to the substring func
    #which will split each feature up into smaller dash-gap chunks
    
    if len(tooLong) > 0:
        
        tooLongLayer = QgsVectorLayer("LineString", "temp", "memory")
        tooLongLayer.setCrs(crs)
        with edit(tooLongLayer):
            tooLongLayer.dataProvider().addFeatures(tooLong)
            
        attribution(tooLongLayer,'Split',True)

        newOnes = contourSubstrings(tooLongLayer)
        
        if newOnes: #this could come back with None so we must check
            additions = newLines(newOnes)
    
    
    params = {
    'LAYERS': [clippedLines,currentHachures],
    'OUTPUT':'TEMPORARY_OUTPUT'
    }
    
    if len(tooLong) > 0:
        if newOnes:
            params['LAYERS'].append(additions)
        
    merged = processing.run("qgis:mergevectorlayers",params)['OUTPUT']
    
    
    return merged

#this takes our lines that need to be clipped off once they touch a contour, and does so
def haircut(contour,toClipLayer):
    params = {
            'INPUT': contour,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
    contourPrePoly = processing.run("qgis:linestopolygons", params)['OUTPUT']
    
    params = {
            'INPUT': contourPrePoly,
            'METHOD': 0,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    contourPoly = processing.run("qgis:fixgeometries", params)['OUTPUT']
    
    params = {
            'INPUT': toClipLayer,
            'OVERLAY': contourPoly,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    clippedLines = processing.run("qgis:difference",params)['OUTPUT']
    
    return clippedLines
    
#this function takes our split dashes and (1) figures out which of our mass of slopelines are candidates, and
#(2) figures out the longest through each dash.

def newLines(splits):
    
    attribution(splits,'Split')
    #first we need the middle point in each line; we grow a slopeline from that middle
    
    instance.addMapLayer(splits, False)
    pointLayers = []
    
    for feat in splits.getFeatures():
        id = feat.id()
        length = feat.attributeMap()['SplitLength']
        splits.selectByIds([id])
    
        params = {
            'INPUT': QgsProcessingFeatureSourceDefinition(splits.source(),selectedFeaturesOnly=True),
            'DISTANCE': length / 2,
            'OUTPUT':'TEMPORARY_OUTPUT'
        }
    
        pointLayers.append(processing.run('qgis:interpolatepoint',params)['OUTPUT'])
    
    pointCoords = [getPointCoords(x) for x in pointLayers]
    
    #we now have a list of all median line points
    #let's next loop through them to plot out the lines
    
    featureList = []
    
    for c in pointCoords:
        lineCoords = [c]
        
        x,y = c
        rc = xy2rc(c) #convert our point to row/col values
        value = getVal(rc,1) #get the aspect value
        
        if value == (-1,-1): #if we go out of bounds, stop this line

            continue
        
        #gotta try to remember trig from 11th grade
        #aspect raster is clockwise from north
        
        value += 180
        newx = x + math.sin(math.radians(value)) * jumpDistance
        newy = y + math.cos(math.radians(value)) * jumpDistance
        
        lineCoords += [(newx,newy)]
        
        #print(lineCoords)
        
        
        for i in range (0,150): 
            #this number is a failsafe in case the other checks below don't catch a line that should be terminated
            #a while loop could maybe lock up here otherwise in some rare cases
            
            x,y = lineCoords[-1]
            rc = xy2rc(lineCoords[-1])
            value = getVal(rc,1) #get the aspect value
            slope = getVal(rc,0) #the slope, too
            if value == (-1,-1): #i.e., we're out of bounds of the raster

                break
            if slope < slopeMin: #if we hit shallow slopes, the lines should end since they'd get clipped off anyway
                break
                
            value += 180
            newx = x + math.sin(math.radians(value)) * jumpDistance
            newy = y + math.cos(math.radians(value)) * jumpDistance
            
            if (newx,newy) in lineCoords:

                break
                
            #lines tend to bounce back and forth as they near a sink. This checks for that.
            #if lines are zig-zagging, every other point should be close to each other.

            if len(lineCoords) > 3 and dist(lineCoords[-1],lineCoords[-3]) < (jumpDistance * 0.5):
                
            #snip off the last one if we've gone bad:
                lineCoords.pop(-1)
                break

            lineCoords += [(newx,newy)]
            
        featureList.append(makeLines(lineCoords))
        
    #now we put our line features into a layer
    slopeLineLayer = QgsVectorLayer('LineString', 'Slopelines', 'memory')
    slopeLineLayer.setCrs(QgsProject.instance().crs())
  
    with edit(slopeLineLayer):    
        slopeLineLayer.dataProvider().addFeatures(featureList)
        
    return slopeLineLayer
        
def dist(one,two):
    x1,y1 = one
    x2,y2 = two
    
    return math.sqrt((x1-x2)**2 + (y1-y2)**2)

def makeLines(coordList):
    #given a list of tuples with xy coords, this generates a line feature connecting them

    points = [QgsPointXY(x, y) for x, y in coordList]
    polyline = QgsGeometry.fromPolylineXY(points)
    feature = QgsFeature()
    feature.setGeometry(polyline)
    
    return feature

def getPointCoords(layer):
    #accepts a layer with a single point and returns a tuple of its coords

    pointFeat = next(layer.getFeatures())
    geo = pointFeat.geometry().asPoint()
    pointCoords = (geo.x(),geo.y())
    
    return(pointCoords)
        
        
def fieldUpdate(layer):
    # Just adding fields was broken before for reasons unknown, so I had to
    # made a new layer and copy everything over, for now
    
    crs = QgsProject.instance().crs()
    
    tempLayer = QgsVectorLayer("LineString", "temp", "memory")
    tempLayer.setCrs(crs)
    with edit(tempLayer):
        tempLayer.dataProvider().addFeatures(layer.getFeatures())
    
    attribution(tempLayer,'Line')
    
    # Update the attributes of the features
    
    return tempLayer



#-----FUNCTIONS OVER------

#-------STEP 1: Process the contours so that they are all in the needed format------
#Each contour will be represented by a polygon showing all areas *higher* than that contour

#First we ned to sort these to ensure we take them in the right order. They probably were already sorted in this order when made
#but let's not chance it.

contourPolys = [(f.id(),f.attributeMap()['ELEV_MIN']) for f in filledContours.getFeatures()]
contourPolys.sort(key = lambda x: x[1])
#this list now holds tuples for each contour of the format (id, elevation)

#---STEP 2A: Let's now make a simple rectangular layer covering the extent of our contours
extent = filledContours.extent()
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

for i in range(0,len(contourPolys)):
    selection = [x[0] for x in contourPolys[0:i]] #grab the contour IDs for contour i and all which are at a lower elevation than it
    filledContours.selectByIds(selection)
    
    params = {
        'INPUT': boundLayer,
        'OUTPUT': 'TEMPORARY_OUTPUT',
        'OVERLAY': QgsProcessingFeatureSourceDefinition(filledContours.source(),selectedFeaturesOnly=True)
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

contourLayer = processing.run("qgis:polygonstolines",params)['OUTPUT']


#----STEP 3: Split our contour layer into a list of layers, each containing one elevation level---#
params = {
        'INPUT': contourLayer,
        'FIELD': 'layer',
        'OUTPUT':'TEMPORARY_OUTPUT'
        }
splitLayers = processing.run('qgis:splitvectorlayer',params)['OUTPUT_LAYERS']

contourLayers = [QgsVectorLayer(path) for path in splitLayers]

#and then we also sort them so that we start with lowest elevation first
contourLayers.sort(key = lambda x: int(list(x.getFeatures())[0].attributeMap()['layer']))
currentHachures = None

#---STEP 4: Iterate through contours to create hachures----#

#as we iterate through, we may find that it takes a few layers before we hit a slope that has lines.
#Early contour lines may easily be in areas where slope < minSlope. So each time, the if statement checks to see if we got anything back.
#Otherwise it moves to the next line and once again tries to generate a starting set of lines.

for layer in contourLayers:
     if currentHachures:
         attribution(currentHachures,'Line')
         currentHachures = spacingCheck(layer)
     else:
         currentHachures = firstLine(layer)
         
attribution(currentHachures,'Line') #update final attributes so that user can filter on line length
currentHachures.setName('Hachures')
instance.addMapLayer(currentHachures)
instance.removeMapLayer(filledContours)

print(time.time() - start)
