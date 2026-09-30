PREFIX nx: <https://cncgaide.org/ontology/nx/1.1#>
PREFIX cg: <https://cncgaide.org/ontology/nx/1.1/pipeline#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>

INSERT {
  GRAPH <{OUT}> {
    ?verdict a cg:Verdict ;
      cg:heuristic cg:H19 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_corner_depth_ratio ; cg:value ?t_corner_depth_ratio ] ;
      cg:value [ a cg:Value ; cg:name "MIN_RADIUS" ; cg:value ?v_MIN_RADIUS ] ;
      cg:value [ a cg:Value ; cg:name "DEPTH" ; cg:value ?v_DEPTH ] ;
      cg:value [ a cg:Value ; cg:name "cornerRadiusToDepth" ; cg:value ?v_cornerRadiusToDepth ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H19 cg:appliesTo ?cls . cg:t_corner_depth_ratio cg:value ?t_corner_depth_ratio . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H19 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:MIN_RADIUS ?v_MIN_RADIUS ; nx:DEPTH ?v_DEPTH }
  FILTER(?v_DEPTH > 0)
  BIND(?v_MIN_RADIUS / ?v_DEPTH AS ?v_cornerRadiusToDepth)
  BIND(IF(?v_cornerRadiusToDepth >= ?t_corner_depth_ratio, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H19")) AS ?verdict)
}
