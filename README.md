# Hachures
A QGIS method to generate automated hachure lines

This is a work in progress. I intend to eventually promote this script within the cartographic community, and potentially do publications and conference presentations on the method. However, first I want some feedback on it from select folks in the community to ensure that it's in good shape.

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
The hachure script will need one more layer: a layer of lines that run up/down the slopes of the terrain. This is similar to doing some hydrological analysis.

First we set up a grid of points covering our terrain. The spacing of these points (in horizontal units of the CRS) is controlled by the `gridSpacing` parameter.
For each point in the grid, we sample the **aspect** raster that we previously generated. The aspect of the terrain (which direction it's facing) is used to draw lines that go up/down the slopes of the terrain. Each of our grid points is the start of a line. The line begins at the grid point, reads the underlying aspect, then jumps in the direction the terrain is facing. Then it samples the raster again, and continues its path. The `jumpDistance` parameter specifies how far it jumps each time.

<img width="664" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/b56fa36c-f517-4139-8c31-d78932715264">

This yields us a whole mess of what I refer to as **slopelines**.
<img width="948" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/559a36b7-0273-4f09-8c8f-4639edb3ff5e">

I originally used a 8-direction flow raster, which showed, for each pixel, which neighboring pixel water would flow into. But, the results were more jagged, whereas these slopelines are smoother, because they can travel at arbitrary angles rather than in one of exactly 8 directions. The `gridSpacing` controls how many lines we get. These lines will form the basis of our hachure lines. I have not yet experimented with how the underlying slopeline density affects the final hachures.

Slopelines have a tendency to bounce around as they approach sinks or flat areas in the terrain. I haven't yet figured out how to control that. For now the script does some rudimentary checks, and stops any slopeline after 150 vertices.

<img width="1118" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/b42c503c-1d50-4a15-b53e-685a4da48dfd">

`jumpDistance` controls how smooth much of the terrain each slopeline reads as it proceeds along. A high number should yield a smoother line.

We now have the pieces needed for generating our hachures. We've generated slope/aspect/contour data from our terrain, and used the aspect raster, plus a grid, to generate slopelines.

# Script 2: Hachure Generator
This script takes the slopelines that we have made, and selectively keeps some parts of them in order to form hachure lines. It also makes use of the slope raster and the contour lines that we generated previously.
## Initial Parameters
The user will need to set a few parameters to begin. `minSpacing` and `maxSpacing` specify, in map units, how close or how far apart we'd like our hachures to be. Meanwhile, `slopeMin` and `slopeMax` specify what slope levels we'll consider in making them. The script makes hachures more dense when the slope of the terrain is higher, and spaces them out farther on shallower terrain. The closer a slope gets toward `slopeMax`, the denser the hachures will be, up to `minSpacing`. If terrain has a slope that is less than `slopeMin`, no hachures will be drawn in that area. If it has a slope equal to or greater than `slopeMax`, hachures will be at maximum density (spaced according to `minSpacing`).

## Contour setup
The script iterates through the contour lines, starting with the lowest-elevation one. Based on how we generated these, this will be a closed loop (or series of closed loops) that, in polygon form, cover all areas **higher** than our contour's elevation.

We begin by divide this contour line into chunks with `splitlinesbylength`. Each chunk is `maxSpacing * 5` in width. This choice is somewhat arbitrary on my part. I want each contour in pieces that are not _too_ big nor _too_ small. Some of the reasoning here will be explained a bit later.

<img width="705" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/b858a338-496d-400a-bed0-c5ae46d8c232">

The script then assigns a few attributes to each split, including an ID number, its length, and most importantly, its average **slope**. Each split chunk is densified with extra vertices (spaced according to the pixel size of the slope raster), and then we use each vertex to sample the slope raster, and average it. So now we know the average slope covered by each split.

## Contour Splitting
Using this slope information, along with the user parameters, we can determine how many slopelines should pass through the zone covered by this particular chunk of a contour line. Its average slope is compared to the `slopeMax` and `slopeMin`, and we use the `minSpacing` and `maxSpacing` parameters to determine how dense the slopelines should be here. Let's say that we have the following parameters:
`minSpacing = 2
maxSpacing = 10
slopeMin = 10
slopeMax = 45`

And let's say our chunk of contour line has an average slope of 35°. That slope of 35° is about 71% of the way from 10° to 45° ((35 - 10) / (45 - 10)). We take that percentage back to our spacing parameters and find the spacing that is 71% of the way between 2 and 10. And here, denser spacing = more slope, so we want the value that is closer to 2 than 10. We get a value of 10 - ((10 - 2) * 0.71) = 4.3. This is our final `spacing` value for our example chunk.

We take that chunk of contour and split it into a series of dashes and gaps, each 4.3 map units in length. We repeat this process for each of the chunks of contours, until each is split into dashes and gaps, and the size of those dashes/gaps varies according to our underlying slope and our user parameters of how much min/max spacing we want. If a chunk's slope is less than `slopeMin`, we eliminate it.

<img width="735" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/d9331072-a77f-44a3-b118-d900771cd230">

This is why I initially split the line into chunks that are `maxSpacing * 5` long. It makes them wide enough that there will be room for a few dashes/gaps, while keeping it small enough to also make sure that it reflects a **local** slope value

## Slopeline Retention

These dashes/gaps (which are adjusted a bit in length based on the length of the actual contour chunk are used to decide which of our many (hundreds of) thousands of slopelines are retained.

To begin, the script takes the original, unbroken contour line, and turns it into a polygon. It then runs an `intersect` with all of the slopelines, effectively clipping off any parts that are outside the contour. Because of the way we set up our contour lines, we only retain the portions of the slopelines that run uphill from the contour lines.

<img width="771" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/cab1fe8b-7b8a-415e-bc01-1da54a29d73c">

The script then effectively answers the following question: for each "dash" in our dash/gap layer, what is the **longest slopeline** that runs through that dash?

<img width="713" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/374e70db-1365-4696-a892-b01b476d9846">

I've prioritized length here, but I'm not sure it's strictly needed. But what _is_ necessary is to retain exactly one line per dash. The gaps (which are `spacing` in width) enforce a **minimum** desired spacing between the slopelines. It prevents them from getting too close.

Due to QGIS being finicky about spatial joins, I actually buffer the contour polygon out a fraction of a unit, so that the clipped-off set of slopelines extend just a little bit beyond the contour dashes, to ensure that they intersect in a way that QGIS can detect. Then the spatial join data is analyzed to find which line to keep.

## Continuing upwards

The script puts these new slopelines in a layer of hachures that we want to keep, and then we move on to the **next** contour line. For this line, and any subsequent one, there are a couple of small changes to the procedure.
For the next contour, we not only split it by length (again, `maxSpacing * 5`), but we also split it based on its intersections with the hachures retained from the prior contour layer(s).

<img width="1340" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/5f86214d-06e5-4942-bdb0-c32733e43a83">

Then we look through each split, get its average slope once again, and once again run the `spacing` calculation to determine how far apart hachures should be in this area based on the underlying slope. This time we take some extra steps. Many of the contour splits seen above are touched on each end by a slopeline; remember the contours were divided by the slopelines (and by `maxSpacing`). So, the length of that contour split encodes how close together the slopelines are. If a contour's ideal spacing (based on the underling slope) is larger than its length, that means that the two slopelines that touch it are **too close together** now according to the underlying slope. We should trim at least one of them off. We look at both slopelines and determine which is the longest, and keep that one and stop the other one here, at this contour. If the local slope is below `slopeMin`, we cut off both as this is an area with a gradual enough slope that no lines should be shown. Here we can see in the middle how one line got cut off:

<img width="508" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/5b93119a-b06e-4b66-900f-9dff1cb81f50">

It started at the outer contour and when it was checked against the next contour on the inside, that slope was too shallow and it was time to cut the line off, while some other lines nearby continued.

The script can also determine which contour chunks are **too long**. If a chunk touches 2 slopelines and is very long, longer than its preferred spacing, it means those slopelines have drifted too far apart for their current slope. We need to start at least 1 new line along this segment. This is done much as it is above: we split that chunk into dashes based on its slope, and then look for the longest lines passing through each part (this can include the existing slopelines).

Finally, some contour chunks may not touch any slopelines, in which case we treat them as normal and split them into varying dash lengths based on the slope, and then give them a line running through each dash.

Iterating through the entire set of contours, we get a set of hachures that are subsets of our giant layer of slopelines. They get clipped off as they get too close, and new lines begin again as they drift apart. Their spacing is controlled by the underlying slope.

<img width="486" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/278f4127-dfae-443a-93b3-82075ea807b8">

I also sometimes filter out the shortest stub lines for a more visually pleasing result.

### Final Thoughts 
A denser `contourInterval` means lines are trimmed/begun more often, because we check their spacing at each contour. Irregular contour intervals would work here, too; it's not important that the contours be evenly spaced. More slopelines means more choices for the script to make about which line is the best running through each dash. That choice of "best" doesn't have to be on length, but that's what I've settled on for now, so that I prioritize hachures that run contiguously.

Getting a good result takes time, and the script can run for several minutes or even hours, depending on the terrain size, and user parameters specified. I am working to make it more efficient, but I counsel patience in running this tool. This is one reason I have split it into two scripts. After running the first one, you may reivew its output and decide to make changes before running the second script, which is the longest to run.
