import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { getDb } from './store.js';

const JWT_SECRET = process.env.JWT_SECRET || 'smartstay-dev-secret-change-me';
const JWT_EXPIRES = '30d';

export function hashPassword(pw) {
  return bcrypt.hashSync(pw, 10);
}

export function verifyPassword(pw, hash) {
  return bcrypt.compareSync(pw, hash);
}

export function signToken(user) {
  return jwt.sign({ uid: user.id }, JWT_SECRET, { expiresIn: JWT_EXPIRES });
}

// Strip sensitive fields before sending a user to the client.
export function publicUser(user) {
  if (!user) return null;
  const { passwordHash, ...rest } = user;
  return rest;
}

// Express middleware — attaches req.user if a valid token is present.
export function authenticate(required = true) {
  return (req, res, next) => {
    const header = req.headers.authorization || '';
    const token = header.startsWith('Bearer ') ? header.slice(7) : null;
    if (!token) {
      if (required) return res.status(401).json({ error: 'Please sign in to continue.' });
      req.user = null;
      return next();
    }
    try {
      const { uid } = jwt.verify(token, JWT_SECRET);
      const user = getDb().users.find((u) => u.id === uid);
      if (!user) throw new Error('User not found');
      req.user = user;
      next();
    } catch {
      if (required) return res.status(401).json({ error: 'Your session expired. Please sign in again.' });
      req.user = null;
      next();
    }
  };
}
