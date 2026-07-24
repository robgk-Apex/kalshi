import { h, mount, $, toast } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate } from '../router.js';
import { loadFavorites } from '../components.js';

function authView(mode) {
  const app = $('#app');
  const isSignup = mode === 'signup';
  const name = h('input', { placeholder: 'Jane Doe', autocomplete: 'name' });
  const email = h('input', { type: 'email', placeholder: 'you@email.com', autocomplete: 'email' });
  const password = h('input', { type: 'password', placeholder: '••••••••', autocomplete: isSignup ? 'new-password' : 'current-password' });
  const asHost = h('input', { type: 'checkbox' });
  const btn = h('button', { class: 'btn btn-primary btn-block btn-lg' }, isSignup ? 'Create account' : 'Log in');

  const submit = async () => {
    btn.disabled = true; btn.textContent = 'Please wait…';
    try {
      const res = isSignup
        ? await api.signup({ name: name.value, email: email.value, password: password.value, isHost: asHost.checked })
        : await api.login({ email: email.value, password: password.value });
      auth.set(res.token, res.user);
      await loadFavorites();
      toast(`Welcome${res.user.name ? ', ' + res.user.name.split(' ')[0] : ''}! 👋`, 'ok');
      navigate('/');
    } catch (err) {
      toast(err.message, 'err');
      btn.disabled = false; btn.textContent = isSignup ? 'Create account' : 'Log in';
    }
  };
  [name, email, password].forEach((el) => el.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); }));
  btn.addEventListener('click', submit);

  const field = (label, node) => h('div', { class: 'field-group' }, h('label', {}, label), node);

  mount(app, h('div', { class: 'auth-wrap' },
    h('div', { class: 'auth-head' }, isSignup ? 'Welcome to SmartStay' : 'Welcome back'),
    h('div', { class: 'auth-body' },
      h('div', { class: 'form' },
        isSignup ? field('Full name', name) : null,
        field('Email', email),
        field('Password', password),
        isSignup ? h('label', { class: 'check' }, asHost, '🏡 I want to host and list my property') : null,
        btn,
        !isSignup ? h('div', { class: 'demo-note' }, 'Try the demo — email ', h('strong', {}, 'guest@smartstay.us'), ', password ', h('strong', {}, 'password123')) : null,
      ),
      h('p', { class: 'center muted', style: { marginTop: '18px' } },
        isSignup ? 'Already have an account? ' : 'New to SmartStay? ',
        h('a', { href: isSignup ? '#/login' : '#/signup', style: { color: 'var(--brand)', fontWeight: 600 } }, isSignup ? 'Log in' : 'Sign up')),
    )));
}

export const loginView = () => authView('login');
export const signupView = () => authView('signup');
