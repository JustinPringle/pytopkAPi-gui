# PyTOPKAPI GUI

-

A description of the GUI's architecture and user experience

-

### Key Objectives

1. Pre-treatment of the catchment to create:
	- DEM
	- Slopes
	- Stream network
	- mannings roughness n in channels
	- mannings roughness n for overland
	- Use soil types to generate:
		- soil depth 
		- saturated soil moisture
	- Use soil texture to generate:
		- residual soil moisture
		- soil conductivity 
2. create input files for the model:
	- rainfall 
	- ET 
	- external flows (if applicable)
	- create global file
3. run the model
4. Analyse the simulation


### DEM processing

This is a tough part of the model, as it requires GRASS to run in the background. But the general flow will be:

1. User opens PyTOKAPI app.
2. A global map is seen. The user can zoom in on their area of interest.
3. User selects an area of interest by drawing a rectangle over the area of interest.
4. If there is no predefined raster the user can download 30m SRTM data.
5. to help construct the catchment input the user must be guided through the following steps:
	1. 	user creates relief with r.relief, can customise outfput filename, can select input file name, user can customise zscale. Allowance must be given to repeat this while the user gets it right. After this is complete an elevation legend placed on the map 
	2. watershed delineation: r.watershed is used to create watersheds (subcatchments). the user needs the choice to set the threshold flag until they are satisfied the watersheds are representitive. r.to_vect is used to convert the raster output to a shape file (vector map). 
	3. To model watersheds for the larger streams within the basin, first set a raster mask to the vector map of the basin with r.mask and then run r.watershed with the threshold set to 1,000 cells at 30 meter resolution (the user may also want to play with the threshold). here is an example code for this step: 
	
```
r.mask vector=basin
r.watershed elevation=elevation_raster threshold=1000 basin=watersheds
r.to.vect -s input=watersheds output=watersheds type=area
d.vect map=watersheds color=white fill_color=none width=1
r.mask -r
```


The user then can optionally layer masked and unmasked shaded relief maps to visualize the topography inside and outside of the basin. First set the mask to the basin with r.mask, then with r.mapcalc use map algebra to create a masked version of the shaded relief. Remove the mask and set the opacity of the original shaded relief map to 50%. the code is:

```
r.mask vector=basin
r.mapcalc expression="masked_relief = shaded_relief"
r.mask -r
```

Flow accumulation and stream ordering is run next. The flow accumulation is computed with r.watershed. Optionally set the -a and -b flags to use positive flow accumulation and beautify flat areas. To better visualize the flow accumulation, drape it over the relief map with r.shade. Add a legend with the -l flag for logarithmic scaling. the code is:

```
r.mask vector=basin
r.watershed -a -b elevation=elevation threshold=10000 accumulation=flow_accumulation
r.shade shade=relief color=flow_accumulation output=shaded_accumulation brighten=80
d.legend -l raster=flow_accumulation at=60,95,2,3.5 font=Lato-Regular fontsize=14
```

Use the r.stream family of modules to extract the stream network and compute the order of the streams. First extract the stream network from the flow accumulation with the module r.stream.extract. Generate raster maps of streams and flow directions. To extract only larger streams set the minimum threshold for flow accumulation to 200. Then use g.extension to install the addon module r.stream.order. Use the digital elevation model, flow accumulation, stream raster, and flow direction maps to compute stream order with r.stream.order. The resulting map of streams will have an attribute table describing the topology of the stream network including Strahler’s, Horton’s, Shreve’s, and Hack’s stream orders. To visualize stream order set the line weight of the vector map of streams to one of the stream order attributes in the table with d.vect. Set the symbol size to zero to hide the stream vertices. Optionally add a scale factor for the line width. Then set the color table to the same stream order attribute with v.colors. the code is:

```
r.stream.extract elevation=elevation accumulation=flow_accumulation threshold=200 stream_raster=stream_raster  direction=flow_direction
r.stream.order stream_rast=stream_raster direction=flow_direction elevation=elevation accumulation=flow_accumulation stream_vect=streams strahler=strahler
r.colors map=strahler color=water
d.vect map=streams width_column=strahler size=0
v.colors map=streams use=attr column=strahler color=water
d.legend raster=strahler at=85,95,2,3.5 font=Lato-Regular fontsize=14
```

The final map should look like:

![](/Users/justinpringle/Documents/projects/pytopkapi-gui/elevation-with-streams.png)














