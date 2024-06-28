# Hachures
A QGIS method to generate automated hachure lines

This is a work in progress. I intend to eventually promote this script to the cartographic community, and potentially do publications and conference presentations on the method. However, first I want some feedback on it from select folks in the community to ensure that it's in good shape.

There are two scripts. The first, "Preparation Work" takes a DEM and generates a variety of layers that will be needed to generate hachures. I separated this out from the main hachure script for now, because a user may wish to run this script, review the results, and maybe adjust parameters further before running the main hachure script, which is the second script.

Let's do a high-level review of how all this works.

# Script 1: Preparation Work
## Initial Parameters
The user must select a DEM raster layer (`iface.activeLayer()`). They should also fill in a few parameters: `gridSpacing`, `jumpDistance`, `contourInterval`. I'll explain each as we go along.

## Generate Raster Derivaties
First off, we take our DEM and generate slope and aspect rasters, as well as a contour polygon layer, using QGIS's existing processes.
The `contourInterval` parameter sets the contour interval, in the map's Z units.
<img width="1472" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/3bcf2980-1fd8-4a3e-acb5-ff8396d34b23">

## Contour Poly Reformatting
The hachure script that we'll eventually run requires that the contours be in a particular format. Initially, the contour polys that we generated show all elevations between two specific values. 
<img width="1331" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/6018a802-2fc9-4de3-9904-d82edf11f7ed">

However, for the hachure process to work, reformatting is needed. For each contour level, we need to generate a polygon that shows all areas that are **higher** than that elevation.
<img width="1307" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/d4517c19-50e9-4044-b603-3ca877206e49">

This is done in the script by creating a layer with a simple rectangle that matches the bounds of the contour layer. For each contour polygon, we subtract it, and all other contours lower than it, from the a copy of the rectangle poly, using the `difference` processing tool. This yields the result we want, as seen in the example above. Finally, we convert those polygons to lines. This yields what the hachure tool requires: closed contours, where the inside of each closure represents all elevations above that contour's value.

## Slopelines
The hachure script will need one more layer: a layer of lines that run up/down the slopes of the terrain.

### Grid Generation
