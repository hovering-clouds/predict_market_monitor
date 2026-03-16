const loginForm = document.getElementById('loginForm');
const passwordInput = document.getElementById('passwordInput');
const loginButton = document.getElementById('loginButton');
const loginStatus = document.getElementById('loginStatus');
const loginParams = new URLSearchParams(window.location.search);
const loginNextTarget = loginParams.get('next') || '/dashboard';

function setLoginStatus(message, kind = 'info') {
  if (!message) {
    loginStatus.className = 'status-banner';
    loginStatus.textContent = '';
    return;
  }

  loginStatus.className = `status-banner ${kind}`;
  loginStatus.textContent = message;
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const password = passwordInput.value;

  if (!password) {
    setLoginStatus('请输入密码。', 'error');
    return;
  }

  loginButton.disabled = true;
  setLoginStatus('正在验证密码...', 'info');

  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password, next: loginNextTarget})
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      setLoginStatus(payload.error || '登录失败。', 'error');
      passwordInput.select();
      return;
    }

    window.location.href = payload.redirect_to || '/dashboard';
  } catch (_) {
    setLoginStatus('无法连接到服务器，请稍后重试。', 'error');
  } finally {
    loginButton.disabled = false;
  }
});

passwordInput.focus();