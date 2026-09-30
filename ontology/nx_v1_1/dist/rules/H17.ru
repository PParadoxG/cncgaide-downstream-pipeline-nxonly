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
      cg:heuristic cg:H17 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_slot_width ; cg:value ?t_slot_width ] ;
      cg:value [ a cg:Value ; cg:name "WIDTH" ; cg:value ?v_WIDTH ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H17 cg:appliesTo ?cls . cg:t_slot_width cg:value ?t_slot_width . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H17 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:WIDTH ?v_WIDTH }
  BIND(IF(?v_WIDTH >= ?t_slot_width, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H17")) AS ?verdict)
}
