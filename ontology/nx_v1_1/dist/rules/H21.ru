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
      cg:heuristic cg:H21 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:tol_draft_zero ; cg:value ?tol_draft_zero ] ;
      cg:value [ a cg:Value ; cg:name "MIN_SIDE_ANGLE" ; cg:value ?v_MIN_SIDE_ANGLE ] ;
      cg:value [ a cg:Value ; cg:name "draftFromVertical" ; cg:value ?v_draftFromVertical ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H21 cg:appliesTo ?cls . cg:tol_draft_zero cg:value ?tol_draft_zero . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H21 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:MIN_SIDE_ANGLE ?v_MIN_SIDE_ANGLE }
  BIND(90 - ?v_MIN_SIDE_ANGLE AS ?v_draftFromVertical)
  BIND(IF(?v_draftFromVertical <= ?tol_draft_zero, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H21")) AS ?verdict)
}
