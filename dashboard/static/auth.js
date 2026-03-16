(function () {
  const AUTH_ERROR_CODE = 'DASHBOARD_AUTH_REQUIRED';

  function redirectToLogin(nextPath) {
    const target = typeof nextPath === 'string' && nextPath
      ? nextPath
      : `${window.location.pathname}${window.location.search}`;
    const params = new URLSearchParams({next: target});
    window.location.href = `/dashboard/login?${params.toString()}`;
  }

  async function fetchWithAuth(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      redirectToLogin();
      const error = new Error(AUTH_ERROR_CODE);
      error.code = AUTH_ERROR_CODE;
      throw error;
    }
    return response;
  }

  function isAuthRequired(error) {
    return Boolean(error && error.code === AUTH_ERROR_CODE);
  }

  window.dashboardAuth = {
    redirectToLogin,
    fetchWithAuth,
    isAuthRequired,
  };
})();