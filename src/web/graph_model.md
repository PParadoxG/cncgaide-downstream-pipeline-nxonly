# The graph model

Everything the system knows lives in one Fuseki dataset (`/nx`) as named
graphs. Nothing is decided from files: what is current is read from the
index graph, and every graph IRI carries the content key that made it.

## Namespaces

| Prefix | IRI | Holds |
| --- | --- | --- |
| `nx:` | `https://cncgaide.org/ontology/nx/1.1#` | NX's own classes and attributes, transcribed from the installed schema |
| `cg:` | `https://cncgaide.org/ontology/nx/1.1/pipeline#` | Everything the pipeline defines: parts, faces, relations, derived quantities, thresholds, heuristics, verdicts, KPI |
| parts | `https://cncgaide.org/parts/<partId>/...` | Instance IRIs (slash IRIs) |
| graphs | `https://cncgaide.org/graph/...` | Named graphs |

## Graphs

| Graph | IRI | Written by | Content |
| --- | --- | --- | --- |
| ontology | `graph/ontology/<ontologyDigest>` | `run.py sync` from `ontology/nx_v1_1/dist/cncgaide_nx.ttl` | Class tree, attribute declarations, ladder section table, relations, derived quantities, thresholds, heuristics with expanded domains and per-class required attributes, KPI types and derivations |
| shapes | `graph/shapes/<ontologyDigest>` | same | SHACL shapes for facts and derived graphs |
| facts | `graph/facts/<partId>/<factsKey>` | the NX journal, loaded by sync | One part: `cg:Part`, `cg:Face`s, features typed by NX class with NX attribute values, attribute gaps, derived quantities with measurements or refusals, `cg:FeatureRelation`s with properties, evidence and terminals |
| derived | `graph/derived/<partId>/<derivedKey>` | the rules | `cg:Verdict`s and `cg:KPIResult`s |
| index | `graph/index` | sync | One `cg:Part` per part with `cg:factsKey`, `cg:derivedKey`, `cg:factsGraph`, `cg:derivedGraph`, `cg:status`, `cg:sourceStep`, `cg:sourceSha256`, `cg:updatedAt` |
| whatif | `graph/whatif/<token>` | `kg.whatif` | A temporary copy of the ontology with changed threshold values; rules are run against it into a temporary derived graph that is never indexed |

Keys: `factsKey = sha256(step)[:12]-sha256(customization_base.xml)[:8]-digest(fact-producing code)[:8]`;
`derivedKey = factsKey-ontologyDigest[:8]-digest(kg/rules.py)[:8]`;
`ontologyDigest = sha256(sourceDigest + buildDigest)[:16]` where `sourceDigest` covers `ontology/nx_v1_1/source/*.yaml` and `buildDigest` covers the generators under `ontology/nx_v1_1/build/` except `gen_page.py`, whose output is presentation only.
A part whose facts key differs from the index needs the NX session again; a part whose derived key differs needs only the rules.

## Facts graph

```
<parts/P>                     a cg:Part ; cg:partId "P" ; cg:sourceStep ; cg:sourceSha256 ; cg:factsKey ; cg:factsGraph <g> ;
                              cg:lengthUnit ; cg:faceCount ; cg:featureCount ; cg:geometricDiameter ; cg:recipe [cg:name; cg:value] ;
                              cg:nx_ugiiLang ; cg:nx_nxReleaseNumber ; cg:unclaimedFace <face> ;
                              cg:derivedSummary [cg:quantity; cg:measured; cg:refused] ; cg:relationCount [cg:relationType; cg:count] .
<parts/P/face/face_12>        a cg:Face ; cg:partOf ; cg:faceId ; cg:surfaceType ; cg:area ; cg:isReversed ; cg:isOuter ;
                              cg:surface_normal | cg:surface_axis_direction | cg:surface_radius ... ; cg:centroid ; cg:bboxMin ; cg:bboxMax ;
                              cg:adjacency [cg:face <face> ; cg:sharedEdge ; cg:concavity] .
<parts/P/feature/STEP2HOLE_001>
                              a nx:STEP2HOLE ; cg:partOf ; cg:nodeId ; rdfs:label "Counter Bore Through Hole" ;
                              nx:DIAMETER_1 26.0 ; nx:DEPTH_1 16.2 ; nx:DEPTH 25.0 ; ...           (NX attribute names, NX values)
                              cg:attributeGap [a cg:AttributeGap ; cg:attribute nx:COLOR ; cg:reason "..."] ;
                              cg:attributeReading [cg:attribute nx:DEPTH_UPPER ; cg:pile "ruleDefault"] ;
                              cg:ownsFace <face> ;
                              cg:derived_min_wall_thickness 3.5 ;                                   (derived quantity, one value)
                              cg:measurement [a cg:Measurement ; cg:quantity cg:derived_min_wall_thickness ; cg:value ; cg:method ; cg:derivedBy ; cg:evidenceFace <face> ; cg:evidence [cg:key; cg:value]] ;
                              cg:measurementRefusal [a cg:MeasurementRefusal ; cg:quantity ; cg:reason] .
<parts/P/relation/hole_spacing_0001>
                              a cg:FeatureRelation ; cg:partOf ; cg:relationId ; cg:relationType cg:HOLE_SPACING ; cg:from <f> ; cg:to <f> ;
                              cg:directed false ; cg:sourceRule ; cg:axisSpacing 42.5 ;               (relation properties from relations.yaml)
                              cg:evidence [cg:key; cg:value] ; cg:diagnostic [cg:key; cg:value] ;
                              cg:terminal [a cg:LocatedOnTerminal ; cg:terminalFeature <f> ; cg:hostOwner <f> ; cg:hostFace <face> ;
                                           cg:terminalRole ; cg:hostSurfaceType ; cg:hostSurfaceNormal] .   (LOCATED_ON only)
```

Vectors are string literals of three decimals separated by spaces. Structured
evidence that is neither scalar nor vector is a `rdf:JSON` literal.

## Derived graph

```
<parts/P/feature/X/verdict/H01>   a cg:Verdict ; cg:heuristic cg:H01 ; cg:target <feature> ; cg:partOf ; cg:scope "feature" ;
                                  cg:outcome cg:PASS | cg:FAIL | cg:NOT_EVALUABLE ;
                                  cg:usedThreshold [cg:threshold cg:t_hole_ld ; cg:value 4] ;
                                  cg:value [a cg:Value ; cg:name "maxRatio" ; cg:value 0.62] ;
                                  cg:gap [cg:attribute nx:DEPTH ; cg:reason "..."] .                 (NOT_EVALUABLE only)
<parts/P/relation/R/verdict/H12>  ... cg:scope "pair" ; cg:targetA <f> ; cg:targetB <f> .
<parts/P/feature/X/kpi/kpi_min_required_tool_length>
                                  a cg:KPIResult ; cg:kpiType cg:kpi_min_required_tool_length ; cg:kpiOfFeature <f> ; cg:partOf ;
                                  cg:kpiValue 25.0 ; cg:kpiUnit "mm" ; cg:derivation cg:kpi_min_required_tool_length .
```

`NOT_APPLICABLE` is never materialised: a feature of a class in a rule's
domain that has no verdict for that rule is not applicable (the rule's
premise did not hold, or the class is outside the domain). `kg.rules.not_applicable_counts`
counts them.

## Ontology graph, the parts rules read

```
cg:H01   a cg:Heuristic ; rdfs:label ; cg:statement ; cg:scope "feature" ; cg:appliesTo nx:STEP1HOLE, ... ;
         cg:requires [cg:onClass nx:STEP2HOLE ; cg:attribute nx:DIAMETER_1, nx:DIAMETER_2, nx:DEPTH_1, nx:DEPTH] ;
         cg:usesThreshold cg:t_hole_ld ; cg:usesRelation ; cg:affectsKpi cg:kpi_machining_time ; cg:publishesValue "maxRatio" ;
         cg:condition "<the SPARQL WHERE body>" .
cg:t_hole_ld  a cg:Threshold ; cg:value 4 ; cg:unit ; skos:definition .      cg:T_v_tool_angles cg:member 30, 45, ... .
nx:STEP2HOLE  a owl:Class ; rdfs:subClassOf nx:STEP1HOLE ; rdfs:label ; cg:abstract false ; cg:recognisable true ; cg:blind false ;
              cg:declaresAttribute nx:DIAMETER_2, ... ;
              cg:section [cg:index 1 ; cg:diameterAttribute nx:DIAMETER_1 ; cg:depthToAttribute nx:DEPTH_1] ,
                         [cg:index 2 ; cg:diameterAttribute nx:DIAMETER_2 ; cg:depthFromAttribute nx:DEPTH_1 ; cg:depthToAttribute nx:DEPTH] ;
              cg:entryDiameterAttribute nx:DIAMETER_1 ; cg:baseDiameterAttribute nx:DIAMETER_2 .
nx:DIAMETER_1 a owl:DatatypeProperty ; rdfs:range xsd:decimal ; cg:dataType "Double" ; cg:unit "Length" ; cg:declaredIn "schema" ; cg:apiReadable true .
```

## Rules

`ontology/nx_v1_1/dist/rules/*.ru` are SPARQL 1.1 Update requests with three
placeholders, `{ONTOLOGY}`, `{FACTS}` and `{OUT}`, substituted by
`kg.rules.run`. `ORDER.txt` fixes the order: the two gate rules (NOT_EVALUABLE
for missing required attributes) first, then one rule per heuristic, then the
KPI derivations. A heuristic rule only fires when every required attribute of
the target's class has a value, so a target gets exactly one verdict per rule.

A rule whose premise rests on a relation reads only the relations the facts
graph carries. Where no relation was proven between two features, the premise
does not hold and the rule writes no verdict, so the target is counted as not
applicable rather than recorded as not evaluable.
