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
      cg:heuristic cg:H07 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_boss_hd ; cg:value ?t_boss_hd ] ;
      cg:value [ a cg:Value ; cg:name "DEPTH" ; cg:value ?v_DEPTH ] ;
      cg:value [ a cg:Value ; cg:name "DIAMETER" ; cg:value ?v_DIAMETER ] ;
      cg:value [ a cg:Value ; cg:name "heightLimit" ; cg:value ?v_heightLimit ] ;
      cg:value [ a cg:Value ; cg:name "heightToDiameter" ; cg:value ?v_heightToDiameter ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H07 cg:appliesTo ?cls . cg:t_boss_hd cg:value ?t_boss_hd . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H07 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:DEPTH ?v_DEPTH ; nx:DIAMETER ?v_DIAMETER }
  FILTER(?v_DIAMETER > 0)
  BIND(?t_boss_hd * ?v_DIAMETER AS ?v_heightLimit)
  BIND(?v_DEPTH / ?v_DIAMETER AS ?v_heightToDiameter)
  BIND(IF(?v_DEPTH <= ?v_heightLimit, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H07")) AS ?verdict)
}
