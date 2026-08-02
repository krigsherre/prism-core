module.exports = {
  queryRewrite: (query, { securityContext }) => {
    const tenantId = (securityContext && securityContext.tenant_id) ? securityContext.tenant_id : 'INVALID_TENANT_ID';

    const cubes = new Set();
    if (query.measures) {
      query.measures.forEach(m => cubes.add(m.split('.')[0]));
    }
    if (query.dimensions) {
      query.dimensions.forEach(d => cubes.add(d.split('.')[0]));
    }

    query.filters = query.filters || [];

    cubes.forEach(cube => {
      query.filters.push({
        member: `${cube}.tenant_id`,
        operator: 'equals',
        values: [tenantId]
      });
    });

    return query;
  }
};
