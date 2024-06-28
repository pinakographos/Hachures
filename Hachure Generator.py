import time
import statistics

#USER PARAMETERS
minSpacing = 2   #(in Map Units)
maxSpacing = 10
spacingRange = maxSpacing - minSpacing

slopeMin = 10 #degrees
slopeMax = 45
slopeRange = slopeMax - slopeMin

#Preparatory work

instance = QgsProject.instance()

crs = instance.crs()
start = time.time()


#Load in the layers we'll need
contourLayer = QgsProject.instance().mapLayersByName('Contour Lines')[0]
lineLayer = QgsProject.instance().mapLayersByName('Slopelines')[0]
slopeLayer = QgsProject.instance().mapLayersByName('Slope')[0]

#CONTOURS FILE MUST BE MULTIRING: all contours of same ELEV value should be the same feature
provider = slopeLayer.dataProvider()
extent = provider.extent()
rows = slopeLayer.height()
cols = slopeLayer.width()
block = provider.block(1, extent, cols, rows)

#every (dash) units, we'll insert a gap of (gap) units
#the gaps ensure that lines are not too close together. The dashes enforce an average spacing
#but the gaps enforce a MINIMUM spacing

def xy2rc(location): #convert x/y coords to row/col
    x,y = location
    
    cellWidth = extent.width() / cols
    cellHeight = extent.height() / rows
    
    col = round((x - extent.xMinimum()) / cellWidth - 0.5)
    row = round((extent.yMaximum() - y) / cellHeight - 0.5)
    
    return (row,col)

def getVal(location):

    row,col = location
    
    
    if row >= rows or col >= cols:
        return 0
        
    if row < 0 or col < 0:
        return 0
    
    return block.value(row,col)
    
#I need to add the same ding-dang attributes to layers so often I might as well make a function
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
    
    
#when given a slope, this determines the spacing of slopelines
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
    #probably would be a hair bit faster to later on densify with some fancy math instead of using qgis processing
    
    
    tempLayer = QgsVectorLayer("LineString", "temp", "memory")
    tempLayer.setCrs(crs)
    with edit(tempLayer):
            tempLayer.dataProvider().addFeatures([contourSnippet])

  
    #ok, add points approximatly every pixel width along the line
    
    avgPixel = 0.5 * (slopeLayer.rasterUnitsPerPixelX() + slopeLayer.rasterUnitsPerPixelY())
    
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
    
    values = [getVal(c) for c in rcTuples]
        
    #this is all the values sampled from the raster. Average it.
    
    try:
        stats = statistics.fmean(values)
    except:
        return 0
    return stats
    

def higherContourSubstrings(tooLongLayer):
    instance.addMapLayer(tooLongLayer,False)
    #this func receives a layer of splits that were "too long" and need 1 or more new slopelines to start among them
    
    outputLines = []
    
    for feature in tooLongLayer.getFeatures():
        slope = feature.attributeMap()['Slope']
        if slope < slopeMin:
            continue
                
        spacing = splitSpacing(slope)
        
        #ok, let's align the dash/gap to the feature length so we get an even split
        #this is much like Illustrator's function to align dashes
        
        totalLength = spacing * 2
        contourLength = feature.geometry().length() - spacing #subtracting this ensures that we have space for gaps on both sides
        totalSplits = round(contourLength / totalLength)
        
        if totalSplits == 0:
            continue
        
        splitLength = contourLength / totalSplits
        adjustDash = splitLength * (spacing / totalLength)

        startPoint = spacing
    
        endPoint = adjustDash + spacing
            
            
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

            startPoint += splitLength
            endPoint += splitLength

            if endPoint > contourLength:

               break

    instance.removeMapLayer(tooLongLayer)
    
    #now let's join together all the output lines

    if len(outputLines) > 0:
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


#this function clips all our slopelines by the contour
#it keeps the part of the slopeline at a higher elevation than the contour

def clipToContour(contourPoly,linesToClip):
     
    #we want to find all flowlines that intersect the poly, so that we only consider flowlines from the contour on up the slope.
    #our slopelines turn to garbage in the vicinity of a sink, so this lets us cut that out.

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


#This function takes a contour line and uses it to thin the slopelines.


    
def longestPerDash(dashLayer,linesToIntersect):
    #takes in a layer of dashes and slopelines, and returns the longest slopeline per dash.

    #here's where we use all those IDs and length fields'
    params = {
        'INPUT' : dashLayer,
        'PREDICATE': [0],
        'JOIN': linesToIntersect,
        'METHOD': 0, # = intersect
        'DISCARD_NONMATCHING':False,
        'OUTPUT':'TEMPORARY_OUTPUT',
        'JOIN_FIELDS': ['LineID','LineLength']
    }

    joinLayer = processing.run('qgis:joinattributesbylocation',params)['OUTPUT']
    #we now know which contour bits are intersected by which slopelines
    
    splits = {}

    for feature in joinLayer.getFeatures():
        splitID = feature.attributeMap()['SplitID']
        lineID = feature.attributeMap()['LineID']
        length = feature.attributeMap()['LineLength']
        
        if splitID in splits:
            splits[splitID] += [(lineID,length)]
        else:
            splits[splitID] = [(lineID,length)]
    
    keepList = []

    for key in splits:
        data = splits[key]
        
        data.sort(key = lambda x: x[1]) #sort to find the longest line that hits this split
        
        keepList.append(data[-1][0])
        
    #keepList now lists the lineID for each line we should keep
    #now let's copy them into a new layer to return

    targets = [f for f in linesToIntersect.getFeatures() if f.attributeMap()['LineID']  in keepList]
    
    tempLayer = QgsVectorLayer("LineString", "temp", "memory")
    tempLayer.setCrs(crs)
    
    with edit(tempLayer):
        tempLayer.dataProvider().addFeatures(targets)
    
    attribution(tempLayer,'Line')
    return tempLayer


#our first step remains the same.

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
            

def firstLine(contour):
    global currentSlopeLines
    #1st we divide initial contour into chunks
   
    params = {
            'INPUT': contour,
            'LENGTH': maxSpacing * 5,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    splitLines = processing.run("qgis:splitlinesbylength",params)['OUTPUT']
    
    #next let's give the splits a needed attribute or two.
    
    pv = splitLines.dataProvider()

    attribution(splitLines,'Split',True)
   
    pv.createSpatialIndex() #this will help future processes go faster

   
    newOnes = higherContourSubstrings(splitLines)
    
    if newOnes:
        additions = makeAdditions(newOnes,contour,currentSlopeLines)
        return additions
    else:
        return None
    

def spacingCheck(contour,linesToCheck):
    global currentSlopeLines
    #1st we run split w/ lines to split the contour according to the existing slopelines
   
    params = {
            'INPUT': contour,
            'LINES': linesToCheck,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    preSplitLines = processing.run("qgis:splitwithlines",params)['OUTPUT']
    
    #we need to then further subdivide this. It's possible that some of the splits
    #are so big that their slope calculations are no longer local

    params = {
            'INPUT': preSplitLines,
            'LENGTH': maxSpacing * 5,
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
        else:
            tooLong.append(feat)
            
    #now we know which splits are (probably) too short and which are (probably) too long
    #and they exist in their own layers
    
    #a "too short" split means that it spans two slopelines that are too close: we need to cut one off
    #"too long" means that we should start a new slope line
    
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
        'JOIN': linesToCheck,
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
    for feat in joinLayer.getFeatures(): # remember that these are polygons. Tiny, tiny polygons.
        
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
    
    targets = [feat for feat in linesToCheck.getFeatures() if feat.attributeMap()['LineID'] in toClip]
    
    #ok, that's the slopelines that need to be cut because they're the shortest of 2
    #also we had some splits that had a slope requiring both lines to be stopped.
    #so let's address that through a similar join process
    
    
    
    toClipLayer = QgsVectorLayer("LineString", "temp", "memory")
    toClipLayer.setCrs(crs)
    with edit(toClipLayer):
        toClipLayer.dataProvider().addFeatures(targets) 
                    
    #and remove them from the existng layer

    with edit(linesToCheck):
        toDelete = [f.id() for f in targets]
        linesToCheck.deleteFeatures(toDelete) 
        
    clippedLines = haircut(contour,toClipLayer)
    
    
    #now we've clipped off some of the lines
    #Let's next deal with adding more in the "too long" splits
    
    #shove all longs into a single layer and pass it to the substring func
    
    if len(tooLong) > 0:
        
        tooLongLayer = QgsVectorLayer("LineString", "temp", "memory")
        tooLongLayer.setCrs(crs)
        with edit(tooLongLayer):
            tooLongLayer.dataProvider().addFeatures(tooLong)
            
        attribution(tooLongLayer,'Split',True)

        newOnes = higherContourSubstrings(tooLongLayer)
        
        additions = makeAdditions(newOnes,contour,currentSlopeLines)
    
    
    params = {
    'LAYERS': [clippedLines,linesToCheck],
    'OUTPUT':'TEMPORARY_OUTPUT'
    }
    
    if len(tooLong) > 1:
        params['LAYERS'].append(additions)
        
    merged = processing.run("qgis:mergevectorlayers",params)['OUTPUT']
    
    return merged

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
    
    


def makeAdditions(splits,contourLayer,currentSlopes):
    global currentSlopeLines
    params = {
            'INPUT': contourLayer,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
    contourPrePoly = processing.run("qgis:linestopolygons", params)['OUTPUT']
    
    
    #now we need to clean this up if it's a multiring'
    
    params = {
            'INPUT': contourPrePoly,
            'METHOD': 0,
            'OUTPUT':'TEMPORARY_OUTPUT'
            }
            
    contourPoly = processing.run("qgis:fixgeometries", params)['OUTPUT']

    
    
    #now since intersections aren't run properly all the time in QGIS (coordinate errors?)
    #we need to adjust our poly just a bit before turning it back to a line

    params = {
            'INPUT': contourPoly,
            'DISTANCE': 0.1, #I'm assuming that I'm working in meters here
            'OUTPUT':'TEMPORARY_OUTPUT'
            }

    biggerPoly = processing.run("qgis:buffer",params)['OUTPUT']
    
    
    currentSlopeLines = clipToContour(biggerPoly,currentSlopes)
    
    #next up spatial join with the slopelines
    linesToAdd = longestPerDash(splits,currentSlopeLines)

    
    
    return linesToAdd
    


#Step 1: clone the slope line layer and save it as a global that we'll access
#We need to store this because we'll keep updating it; we snip more and more of it off over time
#And by using the shrinking layer, we end up running intersections much faster later on

lineLayer.selectAll()
currentSlopeLines = processing.run("qgis:saveselectedfeatures", {'INPUT': lineLayer, 'OUTPUT': 'memory:'})['OUTPUT']
lineLayer.removeSelection()


#Next we split our contour layer into a list of layers, each containing one elevation level
params = {
        'INPUT': contourLayer,
        'FIELD': 'ELEV',
        'OUTPUT':'TEMPORARY_OUTPUT'
        }
splitLayers = processing.run('qgis:splitvectorlayer',params)['OUTPUT_LAYERS']

contourLayers = [QgsVectorLayer(path) for path in splitLayers]

#and then we also sort them so that we start with lowest elevation first
contourLayers.sort(key = lambda x: list(x.getFeatures())[0].attributeMap()['ELEV'])

lineSet = firstLine(contourLayers[0])

#as we iterate through, we may find that it takes a few layers before we hit a slope that has lines


for layer in contourLayers[1:]:
    if lineSet:
        newLineSet = spacingCheck(layer,lineSet)
        cleaned = fieldUpdate(newLineSet)
        lineSet = cleaned
    else:
        lineSet = firstLine(layer)

lineSet.setName('Hachures')
instance.addMapLayer(lineSet)


print(time.time() - start)

