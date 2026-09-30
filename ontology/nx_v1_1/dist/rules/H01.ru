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
      cg:heuristic cg:H01 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_hole_ld ; cg:value ?t_hole_ld ] ;
      cg:value [ a cg:Value ; cg:name "maxRatio" ; cg:value ?v_maxRatio ] ;
      cg:value [ a cg:Value ; cg:name "sectionCount" ; cg:value ?v_sectionCount ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H01 cg:appliesTo ?cls . cg:t_hole_ld cg:value ?t_hole_ld . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H01 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  { SELECT ?f (MAX(?ratio) AS ?v_maxRatio) (COUNT(?s) AS ?v_sectionCount) WHERE {
      GRAPH <{ONTOLOGY}> { ?c cg:section ?s . ?s cg:diameterAttribute ?dp ; cg:depthToAttribute ?tp }
      GRAPH <{FACTS}> { ?f a ?c ; ?dp ?dia ; ?tp ?to }
      { GRAPH <{ONTOLOGY}> { ?s cg:depthFromAttribute ?fp } GRAPH <{FACTS}> { ?f ?fp ?from } }
      UNION
      { GRAPH <{ONTOLOGY}> { ?s cg:index 1 } BIND(0 AS ?from) }
      FILTER(?dia > 0)
      BIND((?to - ?from) / ?dia AS ?ratio)
    } GROUP BY ?f }
  BIND(IF(?v_maxRatio <= ?t_hole_ld, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H01")) AS ?verdict)
}
