#============================USER PARAMETERS============================
# These two params below are in DEM pixel units. So choosing 6 for the
# max_hachure density means the script aims to make hachures 6 px apart
# when the slope is at its minimum

min_hachure_spacing = 4
max_hachure_spacing = 4

# this parameter is how many times we check the hachure spacing
# smaller number runs faster, but if lines are getting too close or too
# far, it's not checking often enough

spacing_checks = 100

# this is the relative slope value used. Values between 0 and 100 should
# be entered. These are enventually converted to the actual slope values
# found in the raster. A min_slope_val of 0 would be converted to the
# lowest slope found in the terrain, and 100 would be converted to the
# highest found.

min_slope_val = 15 #0–100 scale
max_slope_val = 60

# this flag should either be True or False. If True, two hachure outputs
# will be made: one which keeps the lines whole, and which splits them
# into small chunks and adjusts the thickness of each chunk according
# to the underlying slope. Setting this flag to True will increase your
# processing time.

thickness_layer = True

DEM = iface.activeLayer() #The layer of interest must be selected

#============================PREPATORY WORK=============================
#--------STEP 0: Import various modules and such that are needed--------

import math
import statistics
import random

from collections import defaultdict

from qgis.PyQt.QtCore import (
    QVariant
)
from qgis.utils import iface
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsField,
    QgsMemoryProviderUtils,
    QgsProcessingFeatureSourceDefinition,
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    QgsWkbTypes,
    edit
)
from qgis import processing

# This function reports back any errors found later on

def warn_user(error_type):
    # Here are our various error messages and levels
    # The format is ErrorNumber: (Text,Level)
    
    # Wanted to do multi-line strings here for readability, but
    # everything I tried made the popups lose spaces
    
    error_dict = {
        0: ('Done! Enjoy your freshly baked hachures!',
            Qgis.Success),
        1: ('No raster layer selected.',
            Qgis.Critical),
        2: ('min_slope_val must not be less than 0.',
            Qgis.Critical),
        3: ('min_slope_val must be less than max_slope_val.',
            Qgis.Critical),
        4: ('max_slope_val must not be greater than 0.',
            Qgis.Critical),
        5: ('min_hachure_spacing must not be more than max_hachure_spacing.',
            Qgis.Critical),
        6: ('min_hachure_spacing must be greater than 0',
            Qgis.Critical),
        7: ('max_hachure_spacing must be greater than 0',
            Qgis.Critical),
        8: ('min_slope_val was 0. A higher value is recommended to leave flat, unhachured areas.',
            Qgis.Warning),
        9: ('spacing_checks is low. If hachures look too messy, consider raising spacing_checks value.',
            Qgis.Warning),
        10: ('spacing_checks is likely higher than it needs to be to yield clean hachures. Consider lowering this value to speed up processing time.',
            Qgis.Warning),
        11: ('No hachures were generated.',
            Qgis.Critical)
    }
    
    err = error_dict[error_type]
    
    iface.messageBar().pushMessage('Hachure Script',*err)
    
    if err[1] == Qgis.Critical:
        raise Exception(err[0])

#------------------STEP ½: Handling Basic Input Errors------------------

checks = [
    (iface.activeLayer().type() != QgsMapLayer.RasterLayer, 1),
    (min_slope_val < 0,2),
    (min_slope_val >= max_slope_val,3),
    (max_slope_val > 100,4),
    (min_hachure_spacing > max_hachure_spacing,5),
    (min_hachure_spacing <= 0,6),
    (max_hachure_spacing <= 0,7),
    (min_slope_val == 0,8),
    (spacing_checks < 25,9),
    (spacing_checks > 200,10)
]

for condition,code in checks:
    if condition:
        warn_user(code)
        break

#---------STEP 1: Get slope/aspect/contours using built in tools--------
stats = DEM.dataProvider().bandStatistics(1)
elevation_range = stats.maximumValue - stats.minimumValue
contour_interval = elevation_range / spacing_checks

parameters = {
    'INPUT': DEM,
    'BAND': 1,
    'OUTPUT': 'TEMPORARY_OUTPUT'
}
slope_layer = QgsRasterLayer(
    processing.run('qgis:slope', parameters)['OUTPUT'],'Slope')
aspect_layer = QgsRasterLayer(
    processing.run('qgis:aspect', parameters)['OUTPUT'],'Aspect')

parameters['INTERVAL'] = contour_interval
filled_contours = QgsVectorLayer(processing.run('gdal:contour_polygon',
    parameters)['OUTPUT'], "Contour Layer", "ogr")
line_contours = QgsVectorLayer(processing.run('gdal:contour',
    parameters)['OUTPUT'], "Contour Layer", "ogr")

#-----Convert min_slope_val & max_slope_val to actual slope values-----
slope_stats = slope_layer.dataProvider().bandStatistics(1)
slope_maximum = slope_stats.maximumValue
slope_minimum = slope_stats.minimumValue
slope_range = slope_maximum - slope_minimum

min_slope = slope_range * (min_slope_val / 100) + slope_minimum
max_slope = slope_range * (max_slope_val / 100) + slope_minimum

#--------STEP 2: Set up variables & prepare rasters for reading---------
instance = QgsProject.instance()

provider = slope_layer.dataProvider()
extent = provider.extent()
rows = slope_layer.height()
cols = slope_layer.width()
slope_block = provider.block(1, extent, cols, rows)

aspect_block = aspect_layer.dataProvider().block(1, extent, cols, rows)

cell_width = extent.width() / cols
cell_height = extent.height() / rows

average_pixel_size = 0.5 * (slope_layer.rasterUnitsPerPixelX() +
                  slope_layer.rasterUnitsPerPixelY())
jump_distance = average_pixel_size * 3

min_spacing = average_pixel_size * min_hachure_spacing
max_spacing = average_pixel_size * max_hachure_spacing

spacing_range = max_spacing - min_spacing
slope_range = max_slope - min_slope


#===========================CLASS DEFINITIONS===========================
#------Contour lines are used to check the spacing of the hachures------
class Contour:
    def __init__(self,contour_geometry,poly_geometry):
        self.geometry = contour_geometry
        self.polygon = poly_geometry
        
    def ring_list(self):
        # Returns a list of all rings that this contour is made from 
        if self.geometry.isMultipart():
            all_rings = [QgsGeometry.fromPolylineXY(line)
                         for line in self.geometry.asMultiPolyline()]
        else:
            all_rings = [self.geometry]
        return all_rings     
        
    def split_by_hachures(self):
        # Split this contour according to our current list of hachures
        all_segments = []

        for line_geometry in self.ring_list():

            intersection_points = []
            for hachure_feature in current_hachures:
                hachure_geometry = hachure_feature.geometry()
                point = line_geometry.intersection(hachure_geometry)
                if point.wkbType() == QgsWkbTypes.MultiPoint:
                    intersection_points += [CutPoint(
                        QgsGeometry.fromPointXY(p),hachure_feature)
                        for p in point.asMultiPoint()]
                elif point.wkbType() == QgsWkbTypes.Point:
                    intersection_points += [CutPoint(point, hachure_feature)]
                # The intersection can return Empty or (rarely) 
                # a geometryCollection. We can safely skip over these
            
            for point in intersection_points:
                # This tells us where along the line to cut
                point.cut_location = line_geometry.lineLocatePoint(
                                         point.geometry)
                    
            if len(intersection_points) > 0:
                # If we found intersections, use them to cut the ring
                contour_segments = cutpoint_splitter(line_geometry,
                                                intersection_points)
                all_segments += contour_segments
            else:
                # If not, we should still return the unbroken ring
                ring_feature = QgsFeature()
                ring_feature.setGeometry(line_geometry)
                all_segments.append(Segment(ring_feature))
            
        return all_segments
    
#----Segments are contour pieces used to space or generate hachures-----
class Segment:
    def __init__(self,segFeature):
        self.geometry = segFeature.geometry()
        self.length = self.geometry.length()
        self.slope = self.slope()
        self.hachures = []
        
        self.status = None
        # Status stores info on how this segment should affect hachures
        # These values are used later in subsequent_contour
        
        if self.slope < min_slope:
            self.status = 0
        elif self.length < (ideal_spacing(self.slope) * 0.9):
            self.status = 1
        elif self.length > (ideal_spacing(self.slope) * 2.2):
            self.status = 2
        # The 0.9 and 2.2 above are thermostat controls. Instead of a
        # line being "too short" when it exactly falls below its ideal
        # spacing, we let it get a little tighter to avoid near-parallel
        # hachures cycling on/off rapidly.
        
    def ring_list(self):
        return [self.geometry]
        
    def slope(self):
        # Get the average slope under this segment
        densified_line = self.geometry.densifyByDistance(average_pixel_size)
        vertices = [(vertex.x(), vertex.y())
                    for vertex in densified_line.vertices()]
        
        row_col_coords = [xy_to_rc(c) for c in vertices]
        
        samples = [sample_raster(c,0) for c in row_col_coords]

        return statistics.fmean(samples)
    
#--------------CutPoints mark where a contour is to be cut--------------
class CutPoint:
    def __init__(self,point_geometry,hachure_feature):
        self.geometry = point_geometry
        self.hachure = hachure_feature
        self.cut_location = None

#=========================FUNCTION DEFINITIONS-=========================
#--------Converts x/y coords to row/col for sampling the rasters--------
def xy_to_rc(location):
    x,y = location
        
    col = round((x - extent.xMinimum()) / cell_width - 0.5)
    row = round((extent.yMaximum() - y) / cell_height - 0.5)
    
    return (row,col)

#-------------------Samples the slope or aspect raster------------------
def sample_raster(location,type = 0):
    row,col = location
    
    if row >= rows or col >= cols or row < 0 or col < 0:
        # i.e., if we're out of bounds
        return 0
    
    if type == 0:
        return slope_block.value(row,col)
    else:
        return aspect_block.value(row,col)
        
#-----------Given a slope, find the ideal spacing of hachures-----------
def ideal_spacing(slope):
    if slope > max_slope:
        slope = max_slope
    elif slope < min_slope:
        # None indicates that slope is too shallow & needs no hachures
        return None

    # Finds where the slope is in the range of min/max slope
    # Then normalizes it to the range of min/max spacing
    slope_pct = (slope - min_slope) / slope_range
    spacing_qty = slope_pct * spacing_range
    
    spacing = max_spacing - spacing_qty
    
    return spacing
    
#--Take Segments & turn them into dashed lines based on ideal spacing---
def dash_maker(contour_segment_list):
    
    output_segments = []
    
    for contour_segment in contour_segment_list:
        slope = contour_segment.slope
        if slope < min_slope:
            continue
                
        spacing = ideal_spacing(slope)
        
        #We tune the spacing value based on the segment length to ensure
        #an integer number of dashes. This is rather like the automatic
        #dash/gap spacing in Adobe Illustrator

        #Our goal here is to split a segment into dashes & gaps, thusly:
        #  ----    ----    ----    ----    ----    ----    ----
        #Each dash length = spacing, surrounded by gaps half that width
        #Thus one unit looks like this: |  ----  |
        
        total_length = spacing * 2 #the length of a gap + dash + gap
        total_units = round(contour_segment.length / total_length)
        
        if total_units == 0:
            #Just in case we round down to the point of having 0 dashes
            continue
        
        dash_gap_length = contour_segment.length / total_units

        dash_width = dash_gap_length / 2
        #half of our gap-dash-gap is the dash

        gap_width = dash_width / 2
        start_point = gap_width
        end_point = dash_width + gap_width

        geometry = contour_segment.geometry

        while True:
            substring_feature = QgsFeature()
            line_substring = geometry.constGet().curveSubstring(
                start_point, end_point)
            substring_feature.setGeometry(line_substring)

            output_segments.append(Segment(substring_feature))

            start_point += dash_gap_length
            end_point += dash_gap_length

            if end_point > contour_segment.length:
               break

    if len(output_segments) > 0:       
        return output_segments
        
    else:
        return None 
         
#-------------------Starts our first set of hachures--------------------
def first_contour(contour):
    global current_hachures
            
    # Split the contour into even segments to begin
    contour_segments = even_splitter(contour)

    # Then turn them into dashes
    dashes = dash_maker(contour_segments)
    
    if dashes:
        current_hachures = hachure_generator(dashes)
    
#----Checks a contour to see where hachures need to be trimmed/begun----
def subsequent_contour(contour):
    global current_hachures

    # First we split the contour according to the existing hachures
    
    split_contour = contour.split_by_hachures()
    
    # We may need to further subdivide some of these. Some segments may
    # be too long & their slope calculations are no longer local
    
    segment_list = []
    
    for segment in split_contour:
        if segment.length > max_spacing * 3:
            segment_list += even_splitter(segment)
        else:
            segment_list += [segment]

    too_short = []
    too_long = []
    clip_all = []

    for segment in segment_list:
    
        if segment.status == 1:
            too_short.append(segment)
        elif segment.status == 2:
            too_long.append(segment)
        elif segment.status == 0:
            clip_all.append(segment)

    # too_short: this segment spans 2 hachures that are too close
    # too_long: segment's 2 hachures are too far apart
    # clip_all: this segment's slope is low enough that hachures stop
  

    # We first find which hachures must be clipped off
    
    to_clip = []
    
    for seg in clip_all:
        to_clip.extend(seg.hachures)

    for seg in too_short:
        hachures = seg.hachures
        if len(hachures) == 2:
            # Some segments won't touch enough hachures
            random.shuffle(hachures)
            
            to_clip.append(hachures[0])

    # to_clip can have duplicates. A hachure may have too_short segments
    # on each side, and both of them choose that particular hachure as
    # the 1 that needs to be clipped off. So we remove duplicates:
    
    to_clip = list(set(to_clip))
    
    # Remove those to be clipped from the current hachures
    current_hachures = [f for f in current_hachures if f not in to_clip]

    # Clip them, then put them back
    clipped_hachures = haircut(contour,to_clip)
    current_hachures += clipped_hachures
    
    #Let's next deal with adding new hachures to the too_long segments
    
    made_additions = False
    if len(too_long) > 0:
        
        dashes = dash_maker(too_long)
  
        if dashes: #this could come back with None so we must check
            made_additions = True
            additions = hachure_generator(dashes)
    
    if made_additions:
        current_hachures += additions

#----Clips off hachures that need to stop at this particular contour----
def haircut(contour,hachure_list):
    
    contour_poly_geometry = contour.polygon
    
    clipped = []
    for hachure in hachure_list:
        hachure_geo = hachure.geometry()
        feat = QgsFeature()
        feat.setGeometry(hachure_geo.difference(contour_poly_geometry))
        clipped.append(feat)
  
    return clipped

#--Generates new hachures starting at the middle of any given segment---
def hachure_generator(segment_list):

    #First we need the midpoint in each line, to begin our hachure from  
    start_points = []
    
    for segment in segment_list:
        
        midpoint = segment.length / 2
        
        midpoint = segment.geometry.interpolate(midpoint)        
        
        start_points.append(midpoint.asPoint())
    
    #Next loop through the start_points & make hachures
    
    feature_list = []
    
    for coords in start_points:
        line_coords = [coords]
        
        x,y = coords
        rc = xy_to_rc(coords)
        value = sample_raster(rc,1) # 1= Get the aspect value
        
        if value == 0: #if we go out of bounds, stop this line
            continue
        
        #And here I try to recall 11th-grade trigonometry 
        
        new_x = x - math.sin(math.radians(value)) * jump_distance
        new_y = y - math.cos(math.radians(value)) * jump_distance
        
        line_coords += [(new_x,new_y)]
        
        for i in range(0,150):
            # this loop is a failsafe in case other checks below fail
            # to stop the hachure when they should
            
            x,y = line_coords[-1]
            rc = xy_to_rc(line_coords[-1])
            value = sample_raster(rc,1) #get the aspect value
            slope = sample_raster(rc,0) #the slope, too
            if value == 0: # we're out of bounds of the raster
                del line_coords[-1]
                break
            
            if slope < min_slope:
                #if we hit shallow slopes, lines should end
                del line_coords[-1]
                break
                
            value += 180
            new_x = x + math.sin(math.radians(value)) * jump_distance
            new_y = y + math.cos(math.radians(value)) * jump_distance
                
            # Hachures often bounce back and forth in shallow slopes &
            # should stop. If lines are zig-zagging, every other point
            # will be separated by only a small distance

            if (len(line_coords) > 3 and
                dist(line_coords[-1], line_coords[-3])
                < (jump_distance * 1.5)):
                
            # Snip off the last couple points if we've gone bad:
                del line_coords[-2:]
                break

            line_coords += [(new_x,new_y)]
            
        if len(line_coords) > 1:
            # if we stopped before we even got 2 points, don't bother
            feature_list.append(make_lines(line_coords))
    
    return feature_list

#---------------------Cartesian distance calculator---------------------    
def dist(one,two):
    x1,y1 = one
    x2,y2 = two
    
    return math.sqrt((x1-x2)**2 + (y1-y2)**2)

#-------Turns list of tuples of xy coodinates into a line feature-------
def make_lines(coord_list):
    points = [QgsPointXY(x, y) for x, y in coord_list]
    polyline = QgsGeometry.fromPolylineXY(points)
    feature = QgsFeature()
    feature.setGeometry(polyline)
    
    return feature

#-----Splits a line feature into even segments based on max_spacing-----
def even_splitter(contour):
    spacing = max_spacing * 3 
    output_segments = []
        
    for line_geometry in contour.ring_list():
        
        length = line_geometry.length()
        start_point = 0
        end_point = spacing
        
        i = spacing
        cut_locations = []
        while i < length:
            cut_locations.append(i)
            i += spacing
            
        output_segments.extend(master_splitter(line_geometry,cut_locations))

    return output_segments

#---Takes a single line geometry and splits it at a list of locations---
def master_splitter(line_geometry,cut_locations):
    start_point = 0
    cut_locations.append(line_geometry.length())
    cut_locations.sort()
    
    segment_list = []
    
    for cut_spot in cut_locations:
        
        line_substring = line_geometry.constGet().curveSubstring(
                             start_point,cut_spot)
        new_feature = QgsFeature()
        new_feature.setGeometry(line_substring)
        segment_list.append(Segment(new_feature))
        start_point = cut_spot
        
    return segment_list

#---Like master_splitter, but uses CutPoints instead of cut locations---
def cutpoint_splitter(line_geometry,CutPoint_list):
    CutPoint_list.sort(key = lambda x: x.cut_location)
    
    # CutPoints hold info on what hachure generated them; we want to add
    # that info to the subsequent segments
    
    segment_list = []
    
    # Add first segment
    line_substring = line_geometry.constGet().curveSubstring(
                         0,CutPoint_list[0].cut_location)
    new_feature = QgsFeature()
    new_feature.setGeometry(line_substring)
    segment_list.append(Segment(new_feature))

    # Then do all the middle cuts & append hachure data to the Segments
    for i in range(0,len(CutPoint_list)):
        start_point = CutPoint_list[i]
        start_location = start_point.cut_location
        if i == len(CutPoint_list) - 1:
            # Checks if we're at end of the list & handles final segment
            end_location = line_geometry.length()
        else:
            end_point = CutPoint_list[i+1]
            end_location = end_point.cut_location
        line_substring = line_geometry.constGet().curveSubstring(
                             start_location,end_location)
        new_feature = QgsFeature()
        new_feature.setGeometry(line_substring)
        new_segment = Segment(new_feature)
        segment_list.append(new_segment)
        if i != len(CutPoint_list) - 1:
            new_segment.hachures = [start_point.hachure,end_point.hachure]
            
    return segment_list

#===============FUNCTIONS OVER; BEGIN CONTOUR PREPARATION===============
#-STEP 1: Process the contours so that they are all in the needed format

instance.addMapLayer(filled_contours,False)
# Add filled_contours as hidden layer so I can work with it below

# First we sort the contours from low elevation to high.
# They probably were already sorted this way, but let's not chance it.

contour_polys = [f for f in filled_contours.getFeatures()]
contour_polys.sort(key = lambda x: x.attributeMap()['ELEV_MIN'])

# Each contour poly will be turned into a new polygon showing all areas
# that are *higher* than that contour

#-----STEP 2: Make a simple rectangle poly covering contours' extent----
extent = filled_contours.extent()
boundary_polygon = QgsGeometry.fromRect(extent)

#--STEP 3: Iterate through each contour poly and subtract it from our---
#------rectangle, thus yielding rectangles with varying size holes------

contour_geometries = [f.geometry() for f in contour_polys]

# Loop below starts with our boundary rectangle, subtracts the lowest
# elevation poly from it, and stores the result. It then subtracts the
# 2nd-lowest poly from that result and stores that. And so on, each time
# subtracting the next-lowest poly from the result of the last operation

working_geometry = boundary_polygon
contour_differences = []

for geom in contour_geometries[:-1]:
    # We drop the last one because it's going to be empty
    working_geometry = working_geometry.difference(geom)
    contour_differences.append(working_geometry)
    
#------------------STEP 4: Dissolve the contour lines-------------------
contour_dict = defaultdict(list)

for feature in line_contours.getFeatures():
    contour_dict[feature.attributeMap()['ELEV']].append(feature)
    #this dict is now of the form {Elevation: [list of features]}
    
keys = list(contour_dict.keys())
keys.sort()

# we need to sort these low-to-high so they match the order of the
# contour_differences we just generated

dissolved_lines = []
for key in keys:
    geometries = [f.geometry() for f in contour_dict[key]]
    combined_geo = QgsGeometry.collectGeometry(geometries)
    dissolved_lines.append(combined_geo)

# then turn them into Contours for use by the main loop
contour_lines = []    
for dissolved_line,poly_geometry in zip(dissolved_lines,contour_differences):
    contour_lines.append(Contour(dissolved_line,poly_geometry))

#each Contour carrys a record of its corresponding poly for use by haircut

instance.removeMapLayer(filled_contours) # no longer needed
                         
#========MAIN LOOP: Iterate through Contours to generate hachures=======

current_hachures = None

# As we iterate through, it's possible that it takes a few contour lines
# before the slope is high enough (i.e. > min_slope) to make hachures.
# So each time, the if statement checks to see if we got anything back.
# Otherwise it moves to the next line and again tries to generate
# a set of starting hachures.

for line in contour_lines:
     if current_hachures:
         subsequent_contour(line)
     else:
         first_contour(line)

# We sometimes pick up errant duplicates, so let's clean the final list
current_hachures = list(set(current_hachures))

# Also occasionally hachure lines end up being multipart (if they cross
# over a contour line that has a tight bend). So break those open.

separated = []

for hachure in current_hachures:
    geom = hachure.geometry()
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        for part in parts:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPolylineXY(part))
            separated.append(f)
    else:
        separated.append(hachure)

# We should filter out tiny stub features for a pleasant final result

filtered = [f for f in separated
            if f.geometry().length() > jump_distance * 1.5]

# If something went wrong and we got no hachures, let the user know

if filtered == None:
    warn_user(11)

# Add it to the map & also add length attributes so user can filter

hachureLayer = QgsVectorLayer('linestring','Main Hachures','memory')
hachureLayer.setCrs(DEM.crs())

field = QgsField('Length', QVariant.Double)
hachureLayer.dataProvider().addAttributes([field])
hachureLayer.updateFields()

for feature in separated:
    feature.setAttributes([feature.geometry().length()])

with edit(hachureLayer):
    hachureLayer.dataProvider().addFeatures(filtered)
    
instance.addMapLayer(hachureLayer)

#====================OPTIONAL SECTION: SPLIT HACHURES===================

# If the user wants to also generate a layer of split-up hachures that
# use their thickness to encode the slope, this will do that. Only if
# the user parameter of thickness_layer was set True

# this function splits up a hachure line feature
def splitter(feature):
    geo = feature.geometry()
    
    feat_length = geo.length()
    
    # Lines should be split evenly, so we don't have super-tiny stubs
    # The jump_distance is our target length
    
    total_units = round(feat_length/ jump_distance)
    
    #this is how often we split the hachure
    interval = feat_length / total_units 
    
    start = 0
    end = interval
    
    output_features = []

    for i in range(0,total_units):
        line_substring = geo.constGet().curveSubstring(start,end)
        new_feature = QgsFeature()
        new_feature.setGeometry(line_substring)
        output_features.append(new_feature)
        start += interval
        end += interval
    
    return output_features
    
def split_slope(item):
    # Get the average slope under a given segment
    
    densified_line = item.geometry().densifyByDistance(average_pixel_size)
    vertices = [(vertex.x(), vertex.y())
                for vertex in densified_line.vertices()]
    
    row_col_coords = [xy_to_rc(c) for c in vertices]
    
    samples = [sample_raster(c,0) for c in row_col_coords]

    return statistics.fmean(samples)

# Ok, now let's set up a new layer to house our split hachures

if thickness_layer is True:

    splitHachureLayer = QgsVectorLayer('linestring','Split Hachures','memory')
    splitHachureLayer.setCrs(DEM.crs())

    field = QgsField('Slope', QVariant.Double)
    splitHachureLayer.dataProvider().addAttributes([field])
    splitHachureLayer.updateFields()

    splits = []


    # we then split the hachures
    for feature in filtered:
        splits.extend(splitter(feature))

    # and assign them each the average slope in their zone
    for feature in splits:
        feature.setAttributes([split_slope(feature)])

    with edit(splitHachureLayer):
        splitHachureLayer.dataProvider().addFeatures(splits)
        
    instance.addMapLayer(splitHachureLayer)

    # Now make them all black, and vary in size according to their slope
    # ChatGPT wrote a lot of this for me because I had no knowledge of
    # how to adjust symbol rendering in PyQGIS

    # We start with a base black symbol
    base_symbol = QgsLineSymbol.createSimple({
        'color': 'black',
        'width': '0.1mm'
    })

    # Then we set up a graduated symbol renderer tied to the slope field
    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute('Slope')
    renderer.setMode(QgsGraduatedSymbolRenderer.EqualInterval)
    renderer.setGraduatedMethod(Qgis.GraduatedMethod.Size)
    renderer.setSourceSymbol(base_symbol)

    # We set it for 50 classes, so it's practically unclassed
    renderer.updateClasses(splitHachureLayer, 50)

    # By default, 0.1 to 1.0mm will be fine. The user can tweak the layer
    # afterwards to get the desired effect.

    renderer.setSymbolSizes(0.1, 1.0)

    splitHachureLayer.setRenderer(renderer)
    splitHachureLayer.triggerRepaint()
    
warn_user(0)
