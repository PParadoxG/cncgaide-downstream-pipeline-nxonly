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
      cg:heuristic cg:H03 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_pocket_ld ; cg:value ?t_pocket_ld ] ;
      cg:value [ a cg:Value ; cg:name "DEPTH" ; cg:value ?v_DEPTH ] ;
      cg:value [ a cg:Value ; cg:name "WIDTH" ; cg:value ?v_WIDTH ] ;
      cg:value [ a cg:Value ; cg:name "LENGTH" ; cg:value ?v_LENGTH ] ;
      cg:value [ a cg:Value ; cg:name "restrictiveWidth" ; cg:value ?v_restrictiveWidth ] ;
      cg:value [ a cg:Value ; cg:name "depthToMinWidth" ; cg:value ?v_depthToMinWidth ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H03 cg:appliesTo ?cls . cg:t_pocket_ld cg:value ?t_pocket_ld . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H03 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:DEPTH ?v_DEPTH ; nx:WIDTH ?v_WIDTH ; nx:LENGTH ?v_LENGTH }
  BIND(IF(?v_WIDTH < ?v_LENGTH, ?v_WIDTH, ?v_LENGTH) AS ?v_restrictiveWidth)
  FILTER(?v_restrictiveWidth > 0)
  BIND(?v_DEPTH / ?v_restrictiveWidth AS ?v_depthToMinWidth)
  BIND(IF(?v_depthToMinWidth <= ?t_pocket_ld, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H03")) AS ?verdict)
}
