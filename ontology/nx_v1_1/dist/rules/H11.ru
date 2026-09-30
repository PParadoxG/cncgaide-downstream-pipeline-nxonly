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
      cg:heuristic cg:H11 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_floor ; cg:value ?t_floor ] ;
      cg:value [ a cg:Value ; cg:name "derived_floor_thickness" ; cg:value ?v_derived_floor_thickness ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H11 cg:appliesTo ?cls . cg:t_floor cg:value ?t_floor . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H11 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f cg:derived_floor_thickness ?v_derived_floor_thickness }
  BIND(IF(?v_derived_floor_thickness >= ?t_floor, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H11")) AS ?verdict)
}
