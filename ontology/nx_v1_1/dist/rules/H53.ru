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
      cg:heuristic cg:H53 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:T_v_tool_angles ] ;
      cg:usedThreshold [ cg:threshold cg:tol_angle ; cg:value ?tol_angle ] ;
      cg:value [ a cg:Value ; cg:name "ANGLE" ; cg:value ?v_ANGLE ] ;
      cg:value [ a cg:Value ; cg:name "matchingStandardAngles" ; cg:value ?v_matchingStandardAngles ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H53 cg:appliesTo ?cls . cg:tol_angle cg:value ?tol_angle . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H53 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:ANGLE ?v_ANGLE }
  OPTIONAL {
    SELECT ?f (COUNT(?m) AS ?matches) WHERE {
      GRAPH <{FACTS}> { ?f nx:ANGLE ?ang }
      GRAPH <{ONTOLOGY}> { cg:T_v_tool_angles cg:member ?m . cg:tol_angle cg:value ?tol }
      FILTER(ABS(?ang - ?m) <= ?tol)
    } GROUP BY ?f
  }
  BIND(COALESCE(?matches, 0) AS ?v_matchingStandardAngles)
  BIND(IF(?v_matchingStandardAngles > 0, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H53")) AS ?verdict)
}
