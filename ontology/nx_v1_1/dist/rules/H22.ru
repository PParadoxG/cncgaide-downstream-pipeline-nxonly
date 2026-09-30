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
      cg:heuristic cg:H22 ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_pocket_entry_depth ; cg:value ?t_pocket_entry_depth ] ;
      cg:value [ a cg:Value ; cg:name "DEPTH" ; cg:value ?v_DEPTH ] ;
      cg:value [ a cg:Value ; cg:name "entryHoleCount" ; cg:value ?v_entryHoleCount ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H22 cg:appliesTo ?cls . cg:t_pocket_entry_depth cg:value ?t_pocket_entry_depth . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H22 cg:requires ?rq . ?rq cg:onClass ?cls ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?f nx:DEPTH ?v_DEPTH }
  FILTER(?v_DEPTH >= ?t_pocket_entry_depth)
  { SELECT ?f (COUNT(DISTINCT ?h) AS ?v_entryHoleCount) WHERE {
      GRAPH <{FACTS}> { ?f a ?c }
      OPTIONAL {
        GRAPH <{FACTS}> { ?loc cg:relationType cg:LOCATED_ON ; cg:terminal ?t .
                          ?t cg:hostOwner ?f ; cg:terminalFeature ?h . ?h a ?hcls }
        GRAPH <{ONTOLOGY}> { ?hcls rdfs:subClassOf* nx:STEP ; cg:blind true }
      }
    } GROUP BY ?f }
  BIND(IF(?v_entryHoleCount > 0, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?f), "/verdict/H22")) AS ?verdict)
}
