import { h, mount, $, toast } from '../ui.js';
import { api, auth } from '../api.js';
import { navigate, parseHash } from '../router.js';
import { loadFavorites } from '../components.js';

function authView(mode) {
  const app = $('#app');
  const isSignup = mode === 'signup';
  const { query } = parseHash();

  // Role selection (signup only): guest vs property owner.
  let role = query.role === 'host' ? 'host' : 'guest';

  const name = h('input', { placeholder: 'Jane Doe', autocomplete: 'name' });
  const email = h('input', { type: 'email', placeholder: 'you@email.com', autocomplete: 'email' });
  const password = h('input', { type: 'password', placeholder: '••••••••', autocomplete: isSignup ? 'new-password' : 'current-password' });
  const btn = h('button', { class: 'btn btn-primary btn-block btn-lg' });

  const guestCard = h('div', { class: 'role-card', onClick: () => setRole('guest') },
    h('div', { class: 'ico' }, '🧳'), h('b', {}, 'I’m a guest'), h('span', {}, 'Discover & book stays across the USA'));
  const ownerCard = h('div', { class: 'role-card', onClick: () => setRole('host') },
    h('div', { class: 'ico' }, '🏡'), h('b', {}, 'I’m a property owner'), h('span', {}, 'List your home and earn on your terms'));

  const headEl = h('div', { class: 'auth-head' });
  function setRole(r) {
    role = r;
    guestCard.classList.toggle('on', r === 'guest');
    ownerCard.classList.toggle('on', r === 'host');
    btn.textContent = r === 'host' ? 'Create owner account' : 'Create guest account';
    mount(headEl, r === 'host' ? '🏡 Become a SmartStay host' : '🧳 Join SmartStay to book');
  }

  if (isSignup) setRole(role); else { mount(headEl, 'Welcome back'); btn.textContent = 'Log in'; }

  const submit = async () => {
    btn.disabled = true; btn.textContent = 'Please wait…';
    try {
      const res = isSignup
        ? await api.signup({ name: name.value, email: email.value, password: password.value, isHost: role === 'host' })
        : await api.login({ email: email.value, password: password.value });
      auth.set(res.token, res.user);
      await loadFavorites();
      toast(`Welcome${res.user.name ? ', ' + res.user.name.split(' ')[0] : ''}! 👋`, 'ok');
      // Owners land on listing creation; guests go explore.
      navigate(isSignup && role === 'host' ? '/host/new' : (res.user.isHost && !isSignup ? '/host' : '/'));
    } catch (err) {
      toast(err.message, 'err');
      btn.disabled = false; setRole(role);
      if (!isSignup) btn.textContent = 'Log in';
    }
  };
  [name, email, password].forEach((el) => el.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); }));
  btn.addEventListener('click', submit);

  const field = (label, node) => h('div', { class: 'field-group' }, h('label', {}, label), node);

  mount(app, h('div', { class: 'auth-wrap' },
    headEl,
    h('div', { class: 'auth-body' },
      h('div', { class: 'form' },
        isSignup ? h('div', {},
          h('label', { style: { fontSize: '13px', fontWeight: 700, display: 'block', marginBottom: '8px' } }, 'How do you want to use SmartStay?'),
          h('div', { class: 'role-cards' }, guestCard, ownerCard)) : null,
        isSignup ? field('Full name', name) : null,
        field('Email', email),
        field('Password', password),
        btn,
        !isSignup ? h('div', { class: 'demo-note' }, 'Try the demo — email ', h('strong', {}, 'guest@smartstay.us'), ', password ', h('strong', {}, 'password123')) : null,
        isSignup && role === 'host' ? h('p', { class: 'muted center', style: { fontSize: '13px', margin: 0 } }, 'You’ll be taken straight to listing your first property.') : null,
      ),
      h('p', { class: 'center muted', style: { marginTop: '18px' } },
        isSignup ? 'Already have an account? ' : 'New to SmartStay? ',
        h('a', { href: isSignup ? '#/login' : '#/signup', style: { color: 'var(--brand)', fontWeight: 600 } }, isSignup ? 'Log in' : 'Sign up')),
    )));
}

export const loginView = () => authView('login');
export const signupView = () => authView('signup');
