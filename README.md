# Hachures
A QGIS method to generate automated hachure lines. Like these:

<img width="1335" alt="image" src="https://github.com/user-attachments/assets/d4136616-3b73-42eb-8bbd-338f72bc249b">


# Preamble
This is version 2.0, which means hopefully the most severe bugs have been quashed. Meanwhile, if you are stuck, try the sample DEM (of Michigamme Mountain) that is included in this repo. It should succesfully generate hachures within several seconds on a modern computer using the default settings in the script.

Thanks to Nyall Dawson for guiding me toward some significant efficiency gains!

# Advice
First off, **be patient**. This script can take a long time to run, depending on the settings. While a 1000 × 1000px raster with a handful of hachures may process in seconds, if you want a detailed set of lines on a large terrain, it could potentially run for a long time. Start small, and then work your way up to more detail and larger terrains once you get a sense of how long it will take.

Second, you should have a reasonably **smooth terrain** to begin with. Hachures aren’t meant to show a huge amount of detail in a landform. They will gently bend if the terrain is smooth. If the terrain is detailed, the hachures will be jagged. I also note that smoothing the raster tends to _significantly_ speed up the whole script, though I am not wholly sure why.

Finally, I often find the resulting hachures look best if you filter out some of the smallest stubs.

Getting good results takes iteration. Try different settings, and try smoothing your DEM in different ways, and seeing how every adjustment affects the results. A manual hachure artist has a lot of decisions to make about where and how to draw lines. This script will do the drawing for you, but you still need to make the decisions about what parameters look best.

# How to Run
This is a QGIS script, not a plugin, so there's no fancy user interface (I tried, but it turns out that making a plugin was going to be more than I could handle). But it's not too hard to get it running.
+ On this page, go up to the green "Code" button, click it, and select "Download ZIP".
+ Unpack the .ZIP file somewhere on your computer. It contains the script, as well as a test DEM.
+ In QGIS, load in the DEM you want to work with.
+ Then, go to the "Plugins" menu and choose "Python Console." A window will pop up somewhere in your interface.
+ In the Python Console, there's a button that looks like a pencil and paper with the tooltip "Show Editor." Click that. <img width="63" alt="image" src="https://github.com/user-attachments/assets/17a99a69-331d-4d48-b441-f9371855f987" />
+ A new widow will open within the Python Console. In this window is a button that looks like a yellow folder with the tooltip "Open Script…." Click that. <img width="58" alt="image" src="https://github.com/user-attachments/assets/36b66c52-6c9f-49f4-8ca5-d9d7b5c8d24f" />
+ Browse to where you stored the script, and open it.
+ Now you can see the script contents. You can type in values for the user parameters (see below for a discussion).
+ When ready, press the "Run Script" button, which looks like a green arrow <img width="69" alt="image" src="https://github.com/user-attachments/assets/9327f315-7e40-47b6-ba6e-51ab7d654e6a" />. Note that there are **two** green arrows. You want the one that's in the window with the script.
+ Wait patiently for hachures to generate.

# Initial Parameters
The user must select a DEM raster layer (`iface.activeLayer()`). The script comes with some default parameters, but the user may choose to adjust them:
+ `spacing_checks`: How many times the script will check that the hachures are properly spaced. Lowering this runs the script faster. But, it also makes hachure lines more likely to get closer or farther apart than they are supposed to, because they're not being checked often enough. Behind the scenes, this parameter controls how many contour lines we generate across the vertical range of the DEM. Hachure spacing is checked every contour line.
+ `min_hachure_density` and `max_hachure_density`: These specify how close or how far apart we'd like our hachures to be. The units are the pixel size of the DEM.
+ `min_slope_val` and `max_slope_val` specify what slope levels we'll consider in making those hachures. These are relative numbers that range from 0–100. 0 represents the lowest slope value found in the DEM. 100 represents the highest. The script makes hachures more dense when the slope of the terrain is higher, and spaces them out farther on shallower terrain. The closer a slope gets toward `max_slope_val`, the denser the hachures will be, up to `min_hachure_spacing`. If terrain has a slope that is less than `min_slope`, no hachures will be drawn in that area. If it has a slope equal to or greater than `max_slope_val`, hachures will be at maximum density (spaced according to `min_hachure_spacing`).
+ You may also set `thickness_layer` to `True` or to `False`, as you prefer. This generates a second layer in which line thickness varies based on slope. It takes more computation time, so is off by default.

# Walkthrough
I am in the process of writing an article for _Cartographic Perspectives_ which describes, in detail, how this whole method words. Instead of copying all that here, I'll just point you toward [the draft writeup](https://docs.google.com/document/d/1hr_qvdTWrqvuhBJ_qnyXctHCyIyZkPAohMLnucmvHsA/edit?usp=sharing).

# Final Thoughts 
Near the edges of a DEM, you might get some odd hachure lines. I recommend generating hachures on a slightly larger area than you need them. I also usually filter out the shortest stub hachures for a more visually pleasing result.

Getting a good result takes time and iteration. While the example DEM can be processed in seconds with the default script settings, larger terrains and/or greater hachure density will slow things down. It's possible to cause the script to run for hours with the right settings. For large and/or high-detail areas, I recommend starting small (less detail or a smaller raster) to experiment first and find the settings you want, before doing a long run.
