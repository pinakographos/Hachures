# Hachures
A QGIS method to generate automated hachure lines. Like these:

![image](https://github.com/pinakographos/Hachures/assets/5448396/4b00b0da-652b-4a5b-ad4a-5857c175b8c6)

# Preamble
This is version 1.5, which means hopefully the most severe bugs have been quashed. Meanwhile, if you are stuck, try the sample DEM (of Michigamme Mountain) that is included in this repo. It should succesfully generate hachures within several seconds on a modern computer using the default settings in the script.

Thanks to Nyall Dawson for some significant efficiency gains!

# Advice
I'll lead with some of my advice on using the script, and then later on we'll talk about how it works. First off, **be patient**. This script can take a long time to run, depending on the settings. While a 1000 × 1000px raster with a handful of hachures may process in seconds, if you want a detailed set of lines on a large terrain, it could potentially run for a long time. Start small, and then work your way up to more detail and larger terrains once you get a sense of how long it will take.

Second, you should have a reasonably **smooth terrain** to begin with. Hachures aren’t meant to show a huge amount of detail in a landform. They will gently bend if the terrain is smooth. If the terrain is detailed, the hachures will be jagged. I also note that smoothing the raster tends to speed the whole script, though I am not wholly sure why.

Finally, I often find the resulting hachures look best if you filter out some of the smallest stubs.

# Walkthrough
Ok, let's dive into a high-level review of how all this works. My method, built up organically over weeks of trial and error, is perhaps inelegant on account of the nature of its creation process, but it is effective. It is my hope that it will be a platform upon which others (perhaps including me) will build improved methods using fresh ideas.

## Initial Parameters
The user must select a DEM raster layer (`iface.activeLayer()`). The script comes with some default parameters, but the user may choose to adjust them:
+ `spacing_checks`: How many times the script will check that the hachures are properly spaced. Lowering this runs the script faster. But, it also makes hachure lines more likely to get closer or farther apart than they are supposed to. Behind the scenes, this parameter controls how many contour lines we generate across the vertical range of the DEM. Hachure spacing is checked every contour line.
+ `min_hachure_density` and `max_hachure_density`: These specify how close or how far apart we'd like our hachures to be. The units are the pixel size of the DEM.
+ `min_slope` and `max_slope` specify what slope levels we'll consider in making those hachures. The script makes hachures more dense when the slope of the terrain is higher, and spaces them out farther on shallower terrain. The closer a slope gets toward `max_slope`, the denser the hachures will be, up to `min_spacing`. If terrain has a slope that is less than `min_slope`, no hachures will be drawn in that area. If it has a slope equal to or greater than `max_slope`, hachures will be at maximum density (spaced according to `min_spacing`).

## Generate Raster Derivaties
First off, we take our DEM and generate four derivaties:
1. Slope raster
2. Aspect raster
3. Contour polygon layer
4. Contour line layer
For 3 & 4, the script will set the contour interval so that the number of contours generated matches `spacing_checks`.
<img width="1472" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/3bcf2980-1fd8-4a3e-acb5-ff8396d34b23">

## Contour Poly Reformatting
Some retooling of our contours is needed before they are ready. First, the contour lines are dissolved based on their elevation, so that each elevation level has only one feature, which might contain multiple contour rings.

The script primarily uses these contour lines. But, there is one piece of information that they cannot provide, and which the script will need: for a given contour line, without any external information, you cannot tell which areas are _higher_ and which are _lower_ that the elevation of that line.

To fix this, we take our contour polygons and do some processing. Initially, these polys show all elevations between two specific values. 
<img width="1331" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/6018a802-2fc9-4de3-9904-d82edf11f7ed">

However, for each contour level, we need to generate a polygon that shows all areas that are **higher** than that elevation.
<img width="1307" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/d4517c19-50e9-4044-b603-3ca877206e49">

This is done in the script by creating a simple rectangle that matches the bounds of the contour layer. For each contour polygon, we subtract it, and all other contours lower than it, from the rectangle poly, using the `difference` geometry method. This yields the result we want, as seen in the example above. Within the script, we store the polygon and contour line together, so that for any given contour line, we can look up the polygon that shows all areas that are higher elevation than that line.

Now we are ready to begin hachure generation through the main loop of the script.

## Contour Splitting
The script iterates through the contour lines, starting with the lowest-elevation one. We begin by dividing this contour line into chunks, each being `max_spacing * 3` in width (and remember, `max_hachure_spacing` is in units of the DEM's pixels, so that if the DEM pixel width is 12 meters for example, and `max_hachure_spacing` is 3, then `max_hachure_spacing` represents 36 meters). This choice of multiplying by 3 is somewhat arbitrary on my part, but the results seem to work pleasantly enough.

<img width="705" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/b858a338-496d-400a-bed0-c5ae46d8c232">

Each chunk is then densified with extra vertices (spaced according to the pixel size of the slope raster). We use each vertex to sample the slope raster, and average the result. So now we know the average slope covered by each chunk, and store that on the chunk.

## Contours to Dashes
Using this slope information, along with the user parameters, we can determine how many hachures should pass through the zone covered by this particular chunk of a contour line (which the script calls a `Segment`). Its average slope is compared to the `max_slope` and `min_slope`, and we use the `min_hachure_spacing` and `max_hachure_spacing` parameters to determine how dense the hachures should be here. Let's say that we have the following parameters:
+ `min_hachure_spacing = 2`
+ `max_hachure_spacing = 10`
+ `min_slope = 10`
+ `max_slope = 45`

And let's say our segment has an average slope of 35°. That slope of 35° is about 71% of the way from 10° to 45° ((35 - 10) / (45 - 10)). We take that percentage back to our spacing parameters and find the spacing that is 71% of the way between 2 and 10. And here, denser spacing = more slope, so we want the value that is closer to 2 than 10. We get a value of 10 - ((10 - 2) * 0.71) = 4.3. This is our final `spacing` value (in pixels) for our example segment. We take that segment and split it into a series of dashes and gaps, each 4.3 pixels in length.

We repeat this process for each of the segments, until each is split into dashes and gaps, and the size of those dashes/gaps varies according to our underlying slope and our user parameters of how much min/max spacing we want. If a segment's slope is less than `min_slope`, we eliminate it.

<img width="735" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/d9331072-a77f-44a3-b118-d900771cd230">

This is why I initially split the line into chunks that are `max_hachure_spacing * 3` long. It makes them wide enough that there will be room for a few dashes/gaps, while keeping it small enough to also make sure that it reflects a **local** slope value

These dashes/gaps (which are adjusted a bit in length based on the length of the actual segment) are next used to generate hachures.

## Hachure Generation
To begin, we generate a point at the center of each dash. Our hachure lines will grow out of these points, being drawn in an up-slope direction. To begin, we sample the aspect raster and use some trigonometry to calculate which direction is up-slope. We then jump 3 pixels in that direction and then sample the aspect raster again, then jump another 3 pixels up-slope, etc. Connecting the dots, we get a line that runs up the slope: a hachure line.

<img width="1336" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/3c2d7ddc-afac-44db-b70b-5025214e96c1">

The line stops when it hits a shallow slope, or starts to bounce around a sink, or (as a failsafe) when it reaches 150 points long. Else we'll get things like this:

![image](https://github.com/pinakographos/Hachures/assets/5448396/3e92fa2e-0b94-41b5-b371-0f245f29c945)

This hachure generation setup is very akin to some hydrological modelling. I originally experimented with using a flow direction raster, in which each pixel specifies which of its 8 neighboring pixels water would flow into if headed downhill. But, with only 8 directions to choose from, the results were rather jagged, vs. the aspect raster which can have any angle value to specify our next direction (which we take advantage of by skipping a couple pixels over before sampling again). It may still be worth exploring someday — perhaps generating a flow raster as a standalone internal feature in the script, and smoothing out the jagged lines afterwards.

Once we've grown a hachure line from each dash, we store the set of them and move on to the next contour line in the sequence.

Before moving on, I want to note that the reason for starting hachures at these dashes is that making a set of dashes and gaps is used to enforce a **minimum** spacing between hachures. The gaps and dashes ensure that they cannot get too close.

## Continuing Upwards

We now move on to the **next** contour line (the second-lowest one). For this line, and any subsequent ones, the procedure is somewhat different.

For the next contour, we first split it based on its intersections with the hachures retained from the prior contour layer(s). Then any large segments are once again split by maximum length (again, `max_hachure_spacing * 3`).

<img width="1340" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/5f86214d-06e5-4942-bdb0-c32733e43a83">

Then we look through each contour segment, get its average slope, and once again run the `spacing` calculation to determine how far apart hachures should be in this area based on the underlying slope. This time we take some extra steps. Many of the contour segments seen above are touched on each end by a hachure; remember the contours were divided by the hachures (and by `max_hachure_spacing`). So, the length of that contour segment encodes _how close together the hachures are_. If a contour's ideal spacing (based on the underlying slope) is larger than its length, that means that the two hachures that touch it are **too close together** now according to the underlying slope. We should trim one of them off, so that it stops at this contour and does not continue up-slope.
, and the choice is made at random (which ended up looking better than choosing the longest one). If the local slope is below `min_slope`, we cut off both as this is an area with a gradual enough slope that no hachures should be shown. Here we can see in the middle how one line got cut off:

<img width="508" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/5b93119a-b06e-4b66-900f-9dff1cb81f50">

It started at the outer contour and when it was checked against the next contour on the inside, that slope was too shallow and it was time to cut the line off, while some other lines nearby continued. This cut is made using the contour polygons we prepared earlier. Since our hachure passes through the contour, it can tell us which part of the hachure to delete and which to keep, because it encodes which areas are up-slope vs. down-slope of this hachure.

The script can also determine which contour segments are **too long**. If a segments touches 2 hachures and is longer than its preferred spacing, it means those hachures have drifted too far apart for their current slope. We need to start at least 1 new line along this segment. This is done much as it is in the section above: we split that segment into dashes based on its slope, and then begin new hachures at the center of each dash.

Finally, some contour segments may not touch any hachures, in which case we treat them as normal and split them into varying dash lengths based on the slope, and then give them a line running through each dash.

Iterating through the entire set of contours, we get a set of hachures. They get clipped off as they get too close, and new lines begin again as they drift apart. Their spacing is controlled by the underlying slope.

<img width="486" alt="image" src="https://github.com/pinakographos/Hachures/assets/5448396/278f4127-dfae-443a-93b3-82075ea807b8">

### Final Thoughts 
Near the edges of a DEM, you might get some odd hachure lines. I recommend generating hachures on a slightly larger area than you need them. I also usually filter out the shortest stub hachures for a more visually pleasing result.

Getting a good result takes time and iteration. While the example DEM can be processed in seconds with the default script settings, larger terrains and/or greater hachure density will slow things down. It's possible to cause the script to run for hours with the right settings. For large and/or high-detail areas, I recommend starting small (less detail or a smaller raster) to experiment first and find the settings you want, before doing a long run.
