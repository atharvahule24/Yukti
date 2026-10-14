import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BASE_URL,
  sendOtp,
  verifyOtp,
  requestPasswordReset,
  verifyPasswordResetOtp,
  confirmPasswordReset,
  requestUsernameRecovery,
  verifyUsernameRecoveryOtp,
} from '../lib/api';
import { setToken } from '../lib/auth';
import {
  BookOpen,
  Loader2,
  Mail,
  Phone,
  KeyRound,
  ShieldCheck,
  ArrowLeft,
  CheckCircle2,
  User,
} from 'lucide-react';

type AuthMode = 'password' | 'otp' | 'forgot_password' | 'forgot_username';

export function Auth() {
  const [authMode, setAuthMode] = useState<AuthMode>('password');
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // OTP Login state
  const [otpType, setOtpType] = useState<'email' | 'phone'>('email');
  const [otpTarget, setOtpTarget] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // Forgot Password state
  const [fpEmail, setFpEmail] = useState('');
  const [fpOtp, setFpOtp] = useState('');
  const [fpResetToken, setFpResetToken] = useState('');
  const [fpNewPassword, setFpNewPassword] = useState('');
  const [fpConfirmPassword, setFpConfirmPassword] = useState('');
  const [fpStep, setFpStep] = useState<'request' | 'verify' | 'new_password' | 'done'>('request');
  const [fpCooldown, setFpCooldown] = useState(0);

  // Forgot Username state
  const [fuEmail, setFuEmail] = useState('');
  const [fuOtp, setFuOtp] = useState('');
  const [fuStep, setFuStep] = useState<'request' | 'verify' | 'done'>('request');
  const [recoveredUsername, setRecoveredUsername] = useState('');
  const [fuCooldown, setFuCooldown] = useState(0);

  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const resetAllFeedback = () => {
    setError('');
    setSuccessMsg('');
  };

  const startCooldown = (setter: React.Dispatch<React.SetStateAction<number>>, seconds = 60) => {
    setter(seconds);
    const timer = setInterval(() => {
      setter((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // --- Password Login / Register ---
  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const endpoint = isLogin ? '/login' : '/register';
      const res = await fetch(`${BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.message || 'Authentication failed');
      }

      if (isLogin) {
        setToken(data.token);
        navigate('/');
      } else {
        setIsLogin(true);
        setSuccessMsg('Registration successful! Please sign in with your credentials.');
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred during authentication.');
    } finally {
      setLoading(false);
    }
  };

  // --- OTP Login ---
  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await sendOtp(otpTarget, otpType);
      setOtpSent(true);
      setSuccessMsg(res.message || `Verification code sent to your ${otpType}.`);
      startCooldown(setCooldown, res.retry_after || 60);
    } catch (err: any) {
      if (err?.ambiguous_delivery) {
        // Delivery could not be confirmed (e.g. timeout reading provider response),
        // but OTP is preserved in the backend store. Allow entering code without claiming delivery was confirmed.
        setOtpSent(true);
        setError(err.message || 'Delivery could not be confirmed. If you received a code, enter it below.');
        startCooldown(setCooldown, err.retry_after || 60);
      } else {
        setError(err.message || 'Failed to send verification code.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await verifyOtp(otpTarget, otpType, otpCode);
      if (res.token) {
        setToken(res.token);
        navigate('/');
      } else {
        throw new Error('No authentication token received.');
      }
    } catch (err: any) {
      setError(err.message || 'Invalid or expired verification code.');
    } finally {
      setLoading(false);
    }
  };

  // --- Forgot Password Flow ---
  const handleFpRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await requestPasswordReset(fpEmail);
      setFpStep('verify');
      setSuccessMsg(res.message || 'Verification code sent to your registered email.');
      startCooldown(setFpCooldown, res.retry_after || 60);
    } catch (err: any) {
      if (err?.ambiguous_delivery) {
        setFpStep('verify');
        setError(err.message || 'Delivery could not be confirmed. If you received a code, enter it below.');
        startCooldown(setFpCooldown, err.retry_after || 60);
      } else {
        setError(err.message || 'Failed to request password reset code.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleFpVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await verifyPasswordResetOtp(fpEmail, fpOtp);
      if (res.reset_token) {
        setFpResetToken(res.reset_token);
        setFpStep('new_password');
        setSuccessMsg('Code verified! Please choose a new password.');
      } else {
        throw new Error('Verification failed. No reset authorization received.');
      }
    } catch (err: any) {
      setError(err.message || 'Invalid or expired reset code.');
    } finally {
      setLoading(false);
    }
  };

  const handleFpSubmitNewPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();

    if (fpNewPassword !== fpConfirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (fpNewPassword.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }

    setLoading(true);
    try {
      const res = await confirmPasswordReset(fpResetToken, fpNewPassword, fpConfirmPassword);
      setFpStep('done');
      setSuccessMsg(res.message || 'Password reset successfully!');
    } catch (err: any) {
      setError(err.message || 'Failed to update password.');
    } finally {
      setLoading(false);
    }
  };

  // --- Forgot Username Flow ---
  const handleFuRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await requestUsernameRecovery(fuEmail);
      setFuStep('verify');
      setSuccessMsg(res.message || 'Verification code sent to your registered email.');
      startCooldown(setFuCooldown, res.retry_after || 60);
    } catch (err: any) {
      if (err?.ambiguous_delivery) {
        setFuStep('verify');
        setError(err.message || 'Delivery could not be confirmed. If you received a code, enter it below.');
        startCooldown(setFuCooldown, err.retry_after || 60);
      } else {
        setError(err.message || 'Failed to request username recovery code.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleFuVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    resetAllFeedback();
    setLoading(true);

    try {
      const res = await verifyUsernameRecoveryOtp(fuEmail, fuOtp);
      if (res.username) {
        setRecoveredUsername(res.username);
        setFuStep('done');
        setSuccessMsg('Username recovered successfully!');
      } else {
        throw new Error('Recovery failed. No username found for this account.');
      }
    } catch (err: any) {
      setError(err.message || 'Invalid or expired verification code.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)] flex flex-col items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-purple-dim)] blur-[120px] pointer-events-none opacity-50" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-[var(--accent-gold-dim)] blur-[120px] pointer-events-none opacity-30" />

      <div className="w-full max-w-md bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] p-8 relative z-10 shadow-lg">
        {/* Brand Header */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-full flex items-center justify-center mb-4">
            <BookOpen size={24} className="text-[var(--accent-purple)]" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Yukti</h1>
          <p className="text-[var(--text-secondary)] mt-1 text-sm">AI-Powered Personalized Learning</p>
        </div>

        {/* Top Mode Navigation Tabs (Visible when in Password or OTP mode) */}
        {(authMode === 'password' || authMode === 'otp') && (
          <div className="grid grid-cols-2 gap-1 p-1 bg-[var(--bg-elevated)] rounded-lg mb-6 border border-[var(--border)]">
            <button
              type="button"
              onClick={() => {
                setAuthMode('password');
                resetAllFeedback();
              }}
              className={`flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-md transition-all ${
                authMode === 'password'
                  ? 'bg-[var(--accent-purple)] text-white shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <KeyRound size={14} /> Password
            </button>
            <button
              type="button"
              onClick={() => {
                setAuthMode('otp');
                resetAllFeedback();
              }}
              className={`flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-md transition-all ${
                authMode === 'otp'
                  ? 'bg-[var(--accent-purple)] text-white shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <ShieldCheck size={14} /> Email / Phone OTP
            </button>
          </div>
        )}

        {/* Global Feedback Banners */}
        {error && (
          <div role="alert" aria-live="polite" className="p-3 mb-4 rounded-md text-sm bg-[var(--danger-dim)] text-[var(--danger)]">
            {error}
          </div>
        )}

        {successMsg && (
          <div role="status" aria-live="polite" className="p-3 mb-4 rounded-md text-sm bg-[var(--accent-purple-dim)] text-[var(--accent-purple)]">
            {successMsg}
          </div>
        )}

        {/* MODE 1: Standard Password Sign In / Sign Up */}
        {authMode === 'password' && (
          <>
            <form onSubmit={handlePasswordSubmit} className="space-y-4">
              <div>
                <label htmlFor="username" className="block text-sm font-medium mb-1">Username</label>
                <input
                  id="username"
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm font-medium mb-1">Password</label>
                <input
                  id="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                />
              </div>

              {/* Recovery Links in Login Screen */}
              {isLogin && (
                <div className="flex items-center justify-between text-xs pt-1 pb-1">
                  <button
                    type="button"
                    onClick={() => {
                      setAuthMode('forgot_password');
                      setFpStep('request');
                      resetAllFeedback();
                    }}
                    className="text-[var(--accent-purple)] hover:underline focus:outline-none"
                  >
                    Forgot Password?
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAuthMode('forgot_username');
                      setFuStep('request');
                      resetAllFeedback();
                    }}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:underline focus:outline-none"
                  >
                    Forgot Username?
                  </button>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : (isLogin ? 'Sign In' : 'Sign Up')}
              </button>
            </form>

            <div className="mt-6 text-center text-sm text-[var(--text-secondary)]">
              {isLogin ? "Don't have an account? " : "Already have an account? "}
              <button
                onClick={() => {
                  setIsLogin(!isLogin);
                  resetAllFeedback();
                }}
                className="text-[var(--accent-purple)] hover:underline focus:outline-none font-medium"
              >
                {isLogin ? 'Sign up' : 'Sign in'}
              </button>
            </div>
          </>
        )}

        {/* MODE 2: Email & Phone OTP Login */}
        {authMode === 'otp' && (
          <div className="space-y-4">
            <div className="flex gap-2 mb-2">
              <button
                type="button"
                onClick={() => {
                  setOtpType('email');
                  setOtpSent(false);
                  setOtpCode('');
                  resetAllFeedback();
                }}
                className={`flex-1 py-1.5 px-3 rounded text-xs font-medium flex items-center justify-center gap-1.5 border transition-all ${
                  otpType === 'email'
                    ? 'border-[var(--accent-purple)] bg-[var(--accent-purple-dim)] text-[var(--accent-purple)]'
                    : 'border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]'
                }`}
              >
                <Mail size={13} /> Email OTP
              </button>
              <button
                type="button"
                onClick={() => {
                  setOtpType('phone');
                  setOtpSent(false);
                  setOtpCode('');
                  resetAllFeedback();
                }}
                className={`flex-1 py-1.5 px-3 rounded text-xs font-medium flex items-center justify-center gap-1.5 border transition-all ${
                  otpType === 'phone'
                    ? 'border-[var(--accent-purple)] bg-[var(--accent-purple-dim)] text-[var(--accent-purple)]'
                    : 'border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]'
                }`}
              >
                <Phone size={13} /> Phone OTP
              </button>
            </div>

            {!otpSent ? (
              <form onSubmit={handleSendOtp} className="space-y-4">
                <div>
                  <label htmlFor="otp-target" className="block text-sm font-medium mb-1">
                    {otpType === 'email' ? 'Email Address' : 'Phone Number (with Country Code)'}
                  </label>
                  <input
                    id="otp-target"
                    type={otpType === 'email' ? 'email' : 'tel'}
                    required
                    placeholder={otpType === 'email' ? 'student@example.com' : '+1234567890'}
                    value={otpTarget}
                    onChange={(e) => setOtpTarget(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                  <p className="text-xs text-[var(--text-secondary)] mt-1">
                    {otpType === 'email'
                      ? 'We will send a 6-digit verification code to your email.'
                      : 'We will send a 6-digit SMS verification code.'}
                  </p>
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Send Verification Code'}
                </button>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp} className="space-y-4">
                <div>
                  <label htmlFor="otp-code" className="block text-sm font-medium mb-1">
                    Verification Code (6 Digits)
                  </label>
                  <input
                    id="otp-code"
                    type="text"
                    maxLength={6}
                    required
                    placeholder="123456"
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-center text-lg tracking-widest font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Verify Code & Sign In'}
                </button>
                <div className="flex justify-between items-center text-xs pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setOtpSent(false);
                      setOtpCode('');
                      resetAllFeedback();
                    }}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] focus:outline-none"
                  >
                    Change {otpType}
                  </button>
                  <button
                    type="button"
                    disabled={cooldown > 0 || loading}
                    onClick={handleSendOtp}
                    className={`${cooldown > 0 ? 'text-[var(--text-secondary)] cursor-not-allowed' : 'text-[var(--accent-purple)] hover:underline'} focus:outline-none font-medium`}
                  >
                    {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend Code'}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {/* MODE 3: Forgot Password with Mandatory OTP Verification */}
        {authMode === 'forgot_password' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-2 pb-2 border-b border-[var(--border)]">
              <button
                type="button"
                onClick={() => {
                  setAuthMode('password');
                  resetAllFeedback();
                }}
                className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] p-1 rounded-md"
                aria-label="Back to login"
              >
                <ArrowLeft size={16} />
              </button>
              <h2 className="text-base font-semibold">Forgot Password</h2>
            </div>

            {fpStep === 'request' && (
              <form onSubmit={handleFpRequestCode} className="space-y-4">
                <p className="text-xs text-[var(--text-secondary)]">
                  Enter your registered account email to receive a mandatory 6-digit verification code.
                </p>
                <div>
                  <label htmlFor="fp-email" className="block text-sm font-medium mb-1">Email Address</label>
                  <input
                    id="fp-email"
                    type="email"
                    required
                    placeholder="student@example.com"
                    value={fpEmail}
                    onChange={(e) => setFpEmail(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Send Reset Code'}
                </button>
              </form>
            )}

            {fpStep === 'verify' && (
              <form onSubmit={handleFpVerifyCode} className="space-y-4">
                <p className="text-xs text-[var(--text-secondary)]">
                  Enter the 6-digit verification code sent to your email to authorize a password reset.
                </p>
                <div>
                  <label htmlFor="fp-otp" className="block text-sm font-medium mb-1">6-Digit Code</label>
                  <input
                    id="fp-otp"
                    type="text"
                    maxLength={6}
                    required
                    placeholder="123456"
                    value={fpOtp}
                    onChange={(e) => setFpOtp(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-center text-lg tracking-widest font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Verify Code'}
                </button>
                <div className="flex justify-between items-center text-xs pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setFpStep('request');
                      resetAllFeedback();
                    }}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    Change Email
                  </button>
                  <button
                    type="button"
                    disabled={fpCooldown > 0 || loading}
                    onClick={handleFpRequestCode}
                    className={`${fpCooldown > 0 ? 'text-[var(--text-secondary)] cursor-not-allowed' : 'text-[var(--accent-purple)] hover:underline'} font-medium`}
                  >
                    {fpCooldown > 0 ? `Resend in ${fpCooldown}s` : 'Resend Code'}
                  </button>
                </div>
              </form>
            )}

            {fpStep === 'new_password' && (
              <form onSubmit={handleFpSubmitNewPassword} className="space-y-4">
                <div>
                  <label htmlFor="fp-new-pwd" className="block text-sm font-medium mb-1">New Password</label>
                  <input
                    id="fp-new-pwd"
                    type="password"
                    required
                    placeholder="Minimum 8 characters"
                    value={fpNewPassword}
                    onChange={(e) => setFpNewPassword(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <div>
                  <label htmlFor="fp-confirm-pwd" className="block text-sm font-medium mb-1">Confirm New Password</label>
                  <input
                    id="fp-confirm-pwd"
                    type="password"
                    required
                    value={fpConfirmPassword}
                    onChange={(e) => setFpConfirmPassword(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <p className="text-xs text-[var(--text-secondary)]">
                  Must be at least 8 characters long and contain both letters and numbers.
                </p>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Set New Password'}
                </button>
              </form>
            )}

            {fpStep === 'done' && (
              <div className="space-y-4 text-center py-2">
                <div className="w-12 h-12 mx-auto rounded-full bg-[var(--accent-purple-dim)] flex items-center justify-center text-[var(--accent-purple)]">
                  <CheckCircle2 size={28} />
                </div>
                <h3 className="text-sm font-semibold">Password Successfully Reset</h3>
                <p className="text-xs text-[var(--text-secondary)]">
                  All previous sessions have been invalidated. You can now sign in with your new password.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode('password');
                    setIsLogin(true);
                    resetAllFeedback();
                  }}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors shadow-sm"
                >
                  Return to Sign In
                </button>
              </div>
            )}
          </div>
        )}

        {/* MODE 4: Forgot Username with Mandatory OTP Verification */}
        {authMode === 'forgot_username' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-2 pb-2 border-b border-[var(--border)]">
              <button
                type="button"
                onClick={() => {
                  setAuthMode('password');
                  resetAllFeedback();
                }}
                className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] p-1 rounded-md"
                aria-label="Back to login"
              >
                <ArrowLeft size={16} />
              </button>
              <h2 className="text-base font-semibold">Recover Username</h2>
            </div>

            {fuStep === 'request' && (
              <form onSubmit={handleFuRequestCode} className="space-y-4">
                <p className="text-xs text-[var(--text-secondary)]">
                  Enter your registered account email to receive a 6-digit verification code.
                </p>
                <div>
                  <label htmlFor="fu-email" className="block text-sm font-medium mb-1">Email Address</label>
                  <input
                    id="fu-email"
                    type="email"
                    required
                    placeholder="student@example.com"
                    value={fuEmail}
                    onChange={(e) => setFuEmail(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Send Verification Code'}
                </button>
              </form>
            )}

            {fuStep === 'verify' && (
              <form onSubmit={handleFuVerifyCode} className="space-y-4">
                <p className="text-xs text-[var(--text-secondary)]">
                  Enter the 6-digit verification code sent to your email to reveal your username.
                </p>
                <div>
                  <label htmlFor="fu-otp" className="block text-sm font-medium mb-1">6-Digit Code</label>
                  <input
                    id="fu-otp"
                    type="text"
                    maxLength={6}
                    required
                    placeholder="123456"
                    value={fuOtp}
                    onChange={(e) => setFuOtp(e.target.value)}
                    className="w-full bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md px-3 py-2 text-center text-lg tracking-widest font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-purple)] transition-colors"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors flex justify-center items-center shadow-sm"
                >
                  {loading ? <Loader2 size={18} className="animate-spin" /> : 'Verify & Reveal Username'}
                </button>
                <div className="flex justify-between items-center text-xs pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setFuStep('request');
                      resetAllFeedback();
                    }}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    Change Email
                  </button>
                  <button
                    type="button"
                    disabled={fuCooldown > 0 || loading}
                    onClick={handleFuRequestCode}
                    className={`${fuCooldown > 0 ? 'text-[var(--text-secondary)] cursor-not-allowed' : 'text-[var(--accent-purple)] hover:underline'} font-medium`}
                  >
                    {fuCooldown > 0 ? `Resend in ${fuCooldown}s` : 'Resend Code'}
                  </button>
                </div>
              </form>
            )}

            {fuStep === 'done' && (
              <div className="space-y-4 py-2">
                <div className="w-12 h-12 mx-auto rounded-full bg-[var(--accent-purple-dim)] flex items-center justify-center text-[var(--accent-purple)]">
                  <User size={26} />
                </div>
                <div className="p-4 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-md text-center">
                  <span className="text-xs text-[var(--text-secondary)] block mb-1">Your Registered Username:</span>
                  <span className="text-lg font-bold font-mono text-[var(--accent-purple)]">{recoveredUsername}</span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setUsername(recoveredUsername);
                    setAuthMode('password');
                    setIsLogin(true);
                    resetAllFeedback();
                  }}
                  className="w-full bg-[var(--accent-purple)] hover:bg-[var(--accent-purple-hover)] text-white font-medium py-2 rounded-md transition-colors shadow-sm"
                >
                  Sign In With This Username
                </button>
                <div className="text-center">
                  <button
                    type="button"
                    onClick={() => {
                      setAuthMode('password');
                      resetAllFeedback();
                    }}
                    className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    Back to Login
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
