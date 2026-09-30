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
    ?result a cg:KPIResult ;
      cg:kpiType cg:kpi_max_permissible_tool_diameter ;
      cg:kpiOfFeature ?f ;
      cg:partOf ?part ;
      cg:kpiValue ?value ;
      cg:kpiUnit "mm" ;
      cg:derivation cg:kpi_max_permissible_tool_diameter_obround .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:kpi_max_permissible_tool_diameter_obround cg:appliesTo ?cls . }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part . }
  GRAPH <{FACTS}> { ?f nx:LENGTH ?l ; nx:RADIUS ?r }
  BIND(IF(?r > 0 && 2 * ?r < ?l, 2 * ?r, ?l) AS ?value)
  FILTER(BOUND(?value))
  BIND(IRI(CONCAT(STR(?f), "/kpi/kpi_max_permissible_tool_diameter")) AS ?result)
}
