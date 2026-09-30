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
      cg:heuristic cg:H13 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:value [ a cg:Value ; cg:name "holeCount" ; cg:value ?v_holeCount ] ;
      cg:value [ a cg:Value ; cg:name "coaxialHoleCount" ; cg:value ?v_coaxialHoleCount ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H13 cg:appliesTo ?cls .  }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H13 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  { SELECT ?f (COUNT(DISTINCT ?h) AS ?v_holeCount) (COUNT(DISTINCT ?hc) AS ?v_coaxialHoleCount) WHERE {
      GRAPH <{FACTS}> { ?loc cg:relationType cg:LOCATED_ON ; cg:terminal ?t .
                        ?t cg:hostOwner ?f ; cg:terminalFeature ?h . ?h a ?hcls }
      GRAPH <{ONTOLOGY}> { ?hcls rdfs:subClassOf* ?fam }
      VALUES ?fam { nx:STEP nx:HOLES }
      OPTIONAL { GRAPH <{FACTS}> { ?cx cg:relationType cg:COAXIAL .
                                   { ?cx cg:from ?h ; cg:to ?f } UNION { ?cx cg:from ?f ; cg:to ?h } }
                 BIND(?h AS ?hc) }
    } GROUP BY ?f }
  FILTER(?v_holeCount > 0)
  BIND(IF(?v_coaxialHoleCount > 0, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H13")) AS ?verdict)
}
