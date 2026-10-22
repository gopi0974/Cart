import React, { useState, useEffect } from 'react';
import { Users, Shield, UserPlus, CheckCircle, Mail, Key, Trash2 } from 'lucide-react';
import { api } from '../services/api';

export const StaffRolesView: React.FC = () => {
  const [staffList, setStaffList] = useState<any[]>([
    { id: '1', email: 'admin@smartcart.ai', full_name: 'Sarah Jenkins', role: 'ADMIN', is_active: true },
    { id: '2', email: 'security@smartcart.ai', full_name: 'David Kumar', role: 'SECURITY', is_active: true },
    { id: '3', email: 'inventory@smartcart.ai', full_name: 'Priya Sharma', role: 'STAFF', is_active: true },
  ]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'STAFF' });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getStaff?.().then(setStaffList).catch(() => {});
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.email || !form.password || !form.full_name) return;
    setLoading(true);
    try {
      if (api.createStaff) {
        await api.createStaff(form);
      }
      setStaffList([...staffList, { id: String(Date.now()), ...form, is_active: true }]);
      setShowAddModal(false);
      setForm({ email: '', full_name: '', password: '', role: 'STAFF' });
    } catch (err: any) {
      alert(err.message || 'Failed to add staff member.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white flex items-center gap-2">
            <Users className="w-6 h-6 text-emerald-500" />
            Staff Accounts & Access Roles
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Manage store team accounts, administrative privileges, and security alert responder roles.
          </p>
        </div>

        <button
          onClick={() => setShowAddModal(true)}
          className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold px-4 py-2.5 rounded-xl shadow-md shadow-emerald-600/20 inline-flex items-center gap-1.5 transition-all"
        >
          <UserPlus className="w-4 h-4" />
          Add Team Member
        </button>
      </div>

      {/* Staff Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {staffList.map((staff) => (
          <div
            key={staff.id}
            className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-5 shadow-sm space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-2xl bg-slate-900 text-white font-bold text-sm flex items-center justify-center">
                {staff.full_name.slice(0, 2).toUpperCase()}
              </div>
              <span className={`text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full border ${
                staff.role === 'ADMIN'
                  ? 'bg-purple-50 dark:bg-purple-950/60 text-purple-600 border-purple-200 dark:border-purple-800/40'
                  : staff.role === 'SECURITY'
                  ? 'bg-red-50 dark:bg-red-950/60 text-red-600 border-red-200 dark:border-red-800/40'
                  : 'bg-blue-50 dark:bg-blue-950/60 text-blue-600 border-blue-200 dark:border-blue-800/40'
              }`}>
                {staff.role}
              </span>
            </div>

            <div>
              <h3 className="font-semibold text-sm text-slate-900 dark:text-white">
                {staff.full_name}
              </h3>
              <p className="text-xs text-slate-400 flex items-center gap-1 mt-0.5 font-mono">
                <Mail className="w-3 h-3" />
                {staff.email}
              </p>
            </div>

            <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
              <span className="flex items-center gap-1 text-emerald-600">
                <CheckCircle className="w-3.5 h-3.5" />
                Active Account
              </span>
              <span className="font-mono text-[10px] text-slate-400">
                Level 1 Clearance
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Add Staff Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <h3 className="text-lg font-bold font-display text-slate-900 dark:text-white">
              Add New Staff Account
            </h3>
            <form onSubmit={handleCreate} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  placeholder="e.g. Alex Sharma"
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-900 dark:text-white outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="alex@smartcart.ai"
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-900 dark:text-white outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Temporary Password</label>
                <input
                  type="password"
                  required
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="••••••••"
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-900 dark:text-white outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Access Role</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-900 dark:text-white outline-none focus:ring-2 focus:ring-emerald-500 font-semibold"
                >
                  <option value="STAFF">STAFF — Floor Operations & Review Queue</option>
                  <option value="SECURITY">SECURITY — Theft Triage & Cart Lockdowns</option>
                  <option value="ADMIN">ADMIN — Full System Privileges</option>
                </select>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="flex-1 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 font-semibold hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold shadow-md shadow-emerald-600/30"
                >
                  {loading ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
